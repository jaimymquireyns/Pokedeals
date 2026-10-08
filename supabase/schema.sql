-- Plak dit hele bestand in Supabase → SQL Editor → Run. Veilig om opnieuw te draaien.

-- ===================== Gedeelde data (iedereen mag lezen) =====================
create table if not exists sets (
    set_id text primary key,
    name text,
    release_date date,
    card_total int
);

create table if not exists products (
    product_id text primary key,             -- kaarten: TCGdex-id (bijv. sv03.5-125); sealed: 'cm:<Cardmarket-id>'
    kind text not null default 'card' check (kind in ('card', 'sealed')),
    name text not null,
    set_id text, set_name text, number text, set_total int,
    rarity text, image text, category text, product_type text,
    dex_id int, regulation_mark text, legal_standard boolean,
    ppt_id text,                              -- id bij PokemonPriceTracker (tcgPlayerId)
    pk_id text,                               -- id bij PkmnPrices
    printings int, newer_printing boolean,    -- context voor herdrukken (nog niet in de berekening)
    updated_at timestamptz default now()
);
alter table products add column if not exists pk_id text;   -- voor bestaande databases
alter table products add column if not exists pk_miss_on date;   -- wanneer PkmnPrices deze kaart niet kon vinden; pas na PK_MISS_RETRY_DAYS dagen opnieuw zoeken
alter table products add column if not exists cm_url text;           -- exacte Cardmarket-pagina van de kaart (via PkmnPrices); lege tekst = opgevraagd, geen link beschikbaar
alter table products add column if not exists cm_checked_on date;   -- wanneer de Cardmarket-link voor het laatst is opgevraagd (voor de wekelijkse herkansing)
alter table products add column if not exists cm_product_id bigint;   -- Cardmarket-productnummer
alter table products add column if not exists cm_name text;          -- de naam die Cardmarket zelf geeft, mét code, bijv. "Charizard (30C BS4)"; hiermee kan Zoeken ook op Cardmarkets schrijfwijze zoeken
create index if not exists products_name_idx on products (lower(name));
create index if not exists products_number_idx on products (number);
create index if not exists products_ppt_idx on products (ppt_id);

create table if not exists prices (
    product_id text not null references products(product_id) on delete cascade,
    date date not null,
    source text not null default 'tcgdex',    -- tcgdex | cardmarket | ppt (graded) | ppt_hist
    grade_key text not null default 'raw',    -- raw | PSA-10 | BGS-9.5 | CGC-10 ...
    price numeric,                            -- in EUR
    avg1 numeric, avg7 numeric, avg30 numeric, low numeric,
    native numeric, currency text,            -- oorspronkelijke prijs en munt
    primary key (product_id, date, source, grade_key)
);
create index if not exists prices_lookup on prices (product_id, grade_key, date desc);

create table if not exists forecasts (
    product_id text not null references products(product_id) on delete cascade,
    horizon_days int not null,
    threshold_pct int not null,
    price numeric, avg7 numeric, avg30 numeric, mom30 numeric,
    p_up numeric, p_down numeric, exp_change numeric, exp_up numeric, exp_down numeric, score numeric, sigma numeric,
    signal text, mode text, confidence text, n int, basis text,   -- 'trend' (Cardmarket, standaard) of 'nm' (eigen Near Mint-geschiedenis)
    updated date, computed_on date,
    primary key (product_id, horizon_days, threshold_pct)
);
create index if not exists forecasts_lookup on forecasts (horizon_days, threshold_pct, score desc);
alter table forecasts add column if not exists exp_up numeric;   -- voor bestaande databases: moet vóór de views hieronder staan
alter table forecasts add column if not exists exp_down numeric;
alter table forecasts add column if not exists basis text;   -- moet ook vóór de views hieronder staan

create table if not exists market_snapshots (   -- dagelijkse momentopname aanbod/vraag/liquiditeit (market_snapshot.py)
    product_id text not null references products(product_id) on delete cascade,
    date date not null,
    listings int, sellers int, recent_sales int,
    price_usd numeric,
    primary key (product_id, date)
);

create table if not exists card_signals (       -- meersignalenplan: signalen per kaart per dag (signals.py); +1 gunstig, 0 neutraal, -1 ongunstig
    product_id text not null references products(product_id) on delete cascade,
    date date not null,
    price numeric, vs_avg numeric, momentum_14d numeric, cv_14d numeric,
    s_onder_gemiddelde int, s_momentum int, s_stabiliseert int, s_reprint int,
    s_aanbod int, s_vraag int, s_liquiditeit int,
    n_positive int, n_negative int, score int,
    primary key (product_id, date)
);

-- eigen voorspelmodel (edge.py): elke dag vastgelegd, na 30 dagen vergeleken met wat er echt gebeurde
alter table card_signals add column if not exists p_win numeric;     -- kans op winst na alle kosten: nu kopen, over 30 dagen verkopen
alter table card_signals add column if not exists p_win0 numeric;    -- dezelfde kans volgens het kostenbewuste basismodel (zelfde kosten en prijsniveau, geen kenmerken): de lat waar p_win overheen moet
alter table card_signals add column if not exists p_up10 numeric;    -- kans dat de prijs over 30 dagen minstens 10% hoger staat
alter table card_signals add column if not exists exp_ret numeric;   -- verwachte verandering over 30 dagen (0,05 = +5%)
alter table card_signals add column if not exists model text;        -- welke versie van het model dit voorspelde

create table if not exists offers (      -- laagste live aanbiedingen (Cardmarket, via PkmnPrices), alleen Near Mint
    product_id text not null references products(product_id) on delete cascade,
    rank int not null,                        -- 1 = goedkoopste
    price numeric not null,
    seller text, quantity int, language text,
    variant text,                             -- uitvoering: Normal, Reverse Holofoil, ... (vergelijk alleen binnen dezelfde uitvoering)
    date date not null default current_date,  -- wanneer dit is opgehaald, voor de 'bijgewerkt op'-tekst en het ververs-ritme
    primary key (product_id, rank)
);

create table if not exists graded_checks (   -- wat we bij PkmnPrices al aan gegradeerde verkopen hebben opgevraagd (graded_history.py), zodat we niet elke nacht hetzelfde herhalen
    product_id text not null references products(product_id) on delete cascade,
    grade_key text not null,                 -- PSA-10, BGS-9.5, ...
    checked_on date not null,
    n_rows int not null default 0,           -- hoeveel verkopen de laatste opvraging teruggaf
    horizon_days int,                        -- tot hoeveel dagen terug we gekeken hebben
    complete boolean not null default false, -- true = er is niets ouders meer te halen
    primary key (product_id, grade_key)
);
alter table graded_checks enable row level security;   -- alleen voor de collector (service-sleutel); de app leest dit niet

create table if not exists pokemon_interest (   -- Wikipedia-bezoekers per Pokémon (context, nog niet in de berekening)
    dex_id int not null, date date not null, views int,
    primary key (dex_id, date)
);

-- Trackrecord
alter table products add column if not exists nm_hist_days int;   -- tot hoeveel dagen terug de Near Mint-geschiedenis al is opgehaald (card_history.py)

create table if not exists forecast_history (
    product_id text not null references products(product_id) on delete cascade,
    date date not null,
    horizon_days int not null default 30, threshold_pct int not null default 10,
    p_up numeric, price numeric, signal text,
    resolved boolean not null default false,
    primary key (product_id, date, horizon_days, threshold_pct)
);
alter table forecast_history add column if not exists horizon_days int not null default 30;
alter table forecast_history add column if not exists threshold_pct int not null default 10;
alter table forecast_history drop constraint if exists forecast_history_pkey;
alter table forecast_history add primary key (product_id, date, horizon_days, threshold_pct);
create index if not exists forecast_history_due on forecast_history (horizon_days, threshold_pct, resolved, date);   -- trackrecord.fetch_due: snel de na te kijken voorspellingen vinden
create table if not exists trackrecord_stats (
    source text not null,                     -- live | backtest
    horizon_days int not null default 30,
    threshold_pct int not null default 10,
    bucket text not null,                     -- 0-20 | 20-40 | 40-60 | 60-80 | 80-100 | all | koop
    n int not null default 0, hits int not null default 0, sum_p numeric not null default 0,
    primary key (source, horizon_days, threshold_pct, bucket)
);
create table if not exists trackrecord_signals (
    id bigserial primary key,
    product_id text, name text, signal_date date, p_up numeric,
    horizon_days int not null default 30, threshold_pct int not null default 10,
    change numeric, hit boolean, resolved_on date
);
-- Voor bestaande databases: voegt de periode-kolommen toe (bestaande rijen tellen dan als 30 dagen/10%, wat al zo was)
alter table trackrecord_stats add column if not exists horizon_days int not null default 30;
alter table trackrecord_stats add column if not exists threshold_pct int not null default 10;
alter table trackrecord_stats drop constraint if exists trackrecord_stats_pkey;
alter table trackrecord_stats add primary key (source, horizon_days, threshold_pct, bucket);
alter table trackrecord_signals add column if not exists horizon_days int not null default 30;
alter table trackrecord_signals add column if not exists threshold_pct int not null default 10;

-- ===================== Persoonlijke data (alleen je eigen rijen) =====================
create table if not exists collection (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null default auth.uid(),
    product_id text not null references products(product_id) on delete cascade,
    quantity int not null default 1 check (quantity > 0),
    condition text default 'NM',
    grade_company text, grade text,           -- beide leeg = ongegradeerd
    purchase_price numeric not null,
    purchase_date date not null default current_date,
    created_at timestamptz default now()
);
create index if not exists collection_user_idx on collection (user_id);

create table if not exists sales (               -- verkoop als bestelling: een koper, een of meer kaarten
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null default auth.uid(),
    sale_date date not null default current_date,
    buyer text,
    total_price numeric not null,                -- wat de koper voor de kaarten betaalde (zonder verzending)
    shipping_received numeric not null default 0,   -- verzending die de koper betaalde
    shipping_paid numeric not null default 0,       -- wat de verzending jou echt kostte (postzegel)
    commission numeric not null default 0,
    other_costs numeric not null default 0,         -- verpakking e.d.
    note text,
    created_at timestamptz default now()
);
create index if not exists sales_user_idx on sales (user_id);

create table if not exists sale_items (          -- de kaarten in een verkoop, met hun deel van prijs en kosten
    id uuid primary key default gen_random_uuid(),
    sale_id uuid not null references sales(id) on delete cascade,
    user_id uuid not null default auth.uid(),
    product_id text not null references products(product_id) on delete cascade,
    quantity int not null check (quantity > 0),
    condition text, grade_company text, grade text,
    price_share numeric not null,                -- deel van de totaalprijs voor deze stuks
    cost_total numeric not null,                 -- wat deze stuks jou kostten (incl. verzending en kosten bij aankoop)
    purchase_date date
);
create index if not exists sale_items_sale_idx on sale_items (sale_id);

create table if not exists alerts (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null default auth.uid(),
    product_id text not null references products(product_id) on delete cascade,
    grade_key text not null default 'raw',
    min_price numeric, max_price numeric,
    active boolean not null default true,
    armed boolean not null default true,      -- na een melding pas weer 'armed' als de prijs het bereik verlaat
    last_triggered timestamptz,
    unique (user_id, product_id, grade_key)
);

create table if not exists watch_folders (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null default auth.uid(),
    name text not null,
    created_at timestamptz default now(),
    unique (user_id, name)
);

create table if not exists watch_items (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null default auth.uid(),
    product_id text not null references products(product_id) on delete cascade,
    created_at timestamptz default now(),
    unique (user_id, product_id)
);

create table if not exists watch_folder_items (   -- een kaart mag in meerdere mappen staan
    folder_id uuid not null references watch_folders(id) on delete cascade,
    item_id uuid not null references watch_items(id) on delete cascade,
    primary key (folder_id, item_id)
);

create table if not exists user_settings (
    user_id uuid primary key default auth.uid(),
    fee_pct numeric not null default 5,
    ship_eur numeric not null default 1.5,
    net_only boolean not null default true,
    net_min_pct numeric not null default 3,
    digest boolean not null default true,
    price_alerts boolean not null default true,
    horizon int not null default 30,
    attn_pct numeric not null default 15,   -- 'Aandacht nodig': prijsbeweging over 30 dagen vanaf dit percentage
    pct int not null default 10
);

create table if not exists push_subscriptions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null default auth.uid(),
    endpoint text not null unique,
    p256dh text not null, auth text not null,
    created_at timestamptz default now()
);

-- ===================== Views en functies voor de app =====================
drop view if exists v_forecasts;
create view v_forecasts with (security_invoker = on) as
    select f.*, p.kind, p.name, p.set_name, p.number, p.rarity, p.image, p.dex_id
    from forecasts f join products p using (product_id);

drop view if exists v_search;
create view v_search with (security_invoker = on) as
    select p.product_id, p.kind, p.name, p.set_name, p.number, p.set_total, p.rarity, p.image, st.release_date,
           lp.price, f.p_up, f.signal, p.cm_url, p.cm_name
    from products p
    left join sets st on st.set_id = p.set_id
    left join lateral (
        select price from prices pr
        where pr.product_id = p.product_id and pr.grade_key = 'raw'
        order by date desc limit 1) lp on true
    left join forecasts f on f.product_id = p.product_id and f.horizon_days = 30 and f.threshold_pct = 10
    where p.set_id is null or p.set_id !~ '^([AB][0-9]+[a-z]?|P-[A-Z])$';   -- Pokémon TCG Pocket (mobiele game, digitale kaarten) staat niet in de app

alter table offers add column if not exists variant text;
alter table collection add column if not exists purchase_shipping numeric not null default 0;   -- jouw deel van de verzending die je als koper betaalde
alter table user_settings add column if not exists attn_pct numeric not null default 15;   -- 'Aandacht nodig': prijsbeweging over 30 dagen vanaf dit percentage
alter table collection add column if not exists purchase_costs numeric not null default 0;   -- jouw deel van overige aankoopkosten (grading, toploader...)
alter table collection add column if not exists purchase_seller text;                        -- gekocht van
alter table collection add column if not exists purchase_order text;                         -- zelfde waarde = zelfde bestelling
alter table sale_items add column if not exists purchase_seller text;   -- van wie je deze kaart ooit kocht (voor 'Gekocht', ook na verkoop)
alter table sale_items add column if not exists purchase_order text;    -- bij welke aankoop hij hoorde

drop view if exists v_deals;
create view v_deals with (security_invoker = on) as   -- goedkope aanbiedingen (Home): de goedkoopste aanbieding tegen de tweede goedkoopste van dezelfde uitvoering
    with ranked as (
        select o.*, row_number() over (partition by o.product_id, coalesce(o.variant, '') order by o.price, o.rank) as vr
        from offers o),
    pairs as (
        select a.product_id, a.variant, a.price as cheapest, a.seller, a.date, b.price as market
        from ranked a join ranked b
          on b.product_id = a.product_id and coalesce(b.variant, '') = coalesce(a.variant, '') and b.vr = 2
        where a.vr = 1)
    select pr.product_id, pr.variant, pr.cheapest, pr.market, pr.seller, pr.date,
           1 - pr.cheapest / nullif(pr.market, 0) as discount,
           p.name, p.image, p.set_name, p.number, p.kind
    from pairs pr join products p using (product_id)
    where pr.cheapest <= pr.market * 0.8 or pr.market - pr.cheapest >= 25;
grant select on v_deals to anon, authenticated;

drop view if exists v_collection;
create view v_collection with (security_invoker = on) as
    select c.id, c.product_id, c.quantity, c.condition, c.grade_company, c.grade,
           c.purchase_price, c.purchase_shipping, c.purchase_costs, c.purchase_seller, c.purchase_order, c.purchase_date, c.created_at,
           p.kind, p.name, p.set_name, p.number, p.rarity, p.image, p.cm_name,
           lp.price as value_each, lp.date as value_date, p30.price as value_30d_ago,
           f.p_up, f.p_down, f.exp_change, f.signal, f.confidence, f.mode, f.n, f.sigma,
           f.avg7, f.avg30, f.mom30
    from collection c
    join products p using (product_id)
    left join lateral (
        select price, date from prices pr
        where pr.product_id = c.product_id
          and pr.grade_key = case when c.grade_company is null then 'raw' else c.grade_company || '-' || c.grade end
        order by date desc limit 1) lp on true
    left join lateral (
        select price from prices pr
        where pr.product_id = c.product_id
          and pr.grade_key = case when c.grade_company is null then 'raw' else c.grade_company || '-' || c.grade end
          and pr.date <= current_date - 30
        order by date desc limit 1) p30 on true
    left join forecasts f on f.product_id = c.product_id and f.horizon_days = 30 and f.threshold_pct = 10;

drop view if exists latest_prices;
create view latest_prices with (security_invoker = on) as
    select distinct on (product_id) product_id, date, price
    from prices where grade_key = 'raw'
    order by product_id, date desc;

-- Investering en actuele waarde per dag (voor de grafiek in Collectie)
create or replace function portfolio_series(p_days int default 30)
returns table (day date, invested numeric, value numeric)
language sql stable security invoker as $$
    select d::date,
           coalesce(sum(c.quantity * c.purchase_price + c.purchase_shipping + c.purchase_costs) filter (where c.purchase_date <= d::date), 0),
           coalesce(sum(c.quantity * coalesce(lp.price, c.purchase_price)) filter (where c.purchase_date <= d::date), 0)
    from generate_series(current_date - p_days, current_date, interval '1 day') d
    cross join collection c
    left join lateral (
        select price from prices pr
        where pr.product_id = c.product_id
          and pr.grade_key = case when c.grade_company is null then 'raw' else c.grade_company || '-' || c.grade end
          and pr.date <= d::date
        order by pr.date desc limit 1) lp on true
    group by d order by d
$$;

drop view if exists v_watchlist;
create view v_watchlist with (security_invoker = on) as
    select w.id, w.product_id, w.created_at,
           p.kind, p.name, p.set_name, p.number, p.rarity, p.image,
           lp.price as value_each, lp.date as value_date,
           f.p_up, f.p_down, f.exp_change, f.exp_up, f.exp_down, f.signal, f.confidence, f.mode, f.n
    from watch_items w
    join products p using (product_id)
    left join lateral (
        select price, date from prices pr
        where pr.product_id = w.product_id and pr.grade_key = 'raw'
        order by date desc limit 1) lp on true
    left join forecasts f on f.product_id = w.product_id and f.horizon_days = 30 and f.threshold_pct = 10;

-- ===================== Beveiliging =====================
alter table sets enable row level security;
alter table products enable row level security;
alter table prices enable row level security;
alter table forecasts enable row level security;
alter table pokemon_interest enable row level security;
alter table offers enable row level security;
alter table market_snapshots enable row level security;
alter table card_signals enable row level security;
alter table forecast_history enable row level security;
alter table trackrecord_stats enable row level security;
alter table trackrecord_signals enable row level security;
alter table collection enable row level security;
alter table alerts enable row level security;
alter table user_settings enable row level security;
alter table push_subscriptions enable row level security;
alter table watch_folders enable row level security;
alter table watch_items enable row level security;
alter table watch_folder_items enable row level security;
alter table sales enable row level security;
alter table sale_items enable row level security;

do $$
declare t text;
begin
    foreach t in array array['sets','products','prices','forecasts','pokemon_interest','trackrecord_stats','trackrecord_signals','offers','market_snapshots','card_signals'] loop
        execute format('drop policy if exists "public read" on %I', t);
        execute format('create policy "public read" on %I for select to anon, authenticated using (true)', t);
    end loop;
    foreach t in array array['collection','alerts','user_settings','push_subscriptions','watch_folders','watch_items','sales','sale_items'] loop
        execute format('drop policy if exists "own rows" on %I', t);
        execute format('create policy "own rows" on %I for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid())', t);
    end loop;
end $$;

grant select on sets, products, prices, forecasts, pokemon_interest, trackrecord_stats, trackrecord_signals, offers, market_snapshots, card_signals to anon, authenticated;
grant select on v_forecasts, v_search to anon, authenticated;
grant select on v_collection to authenticated;
grant select on v_watchlist to authenticated;
grant select on latest_prices to service_role;
grant execute on function portfolio_series(int) to authenticated;
grant select, insert, update, delete on collection, alerts, user_settings, push_subscriptions, watch_folders, watch_items, watch_folder_items, sales, sale_items to authenticated;

drop policy if exists "own rows" on watch_folder_items;
create policy "own rows" on watch_folder_items for all to authenticated
    using (exists (select 1 from watch_folders f where f.id = folder_id and f.user_id = auth.uid()))
    with check (exists (select 1 from watch_folders f where f.id = folder_id and f.user_id = auth.uid())
                and exists (select 1 from watch_items i where i.id = item_id and i.user_id = auth.uid()));
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;

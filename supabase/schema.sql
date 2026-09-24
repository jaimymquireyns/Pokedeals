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

create table if not exists offers (      -- laagste live aanbiedingen (Cardmarket, via PkmnPrices), alleen Near Mint
    product_id text not null references products(product_id) on delete cascade,
    rank int not null,                        -- 1 = goedkoopste
    price numeric not null,
    seller text, quantity int, language text,
    date date not null default current_date,  -- wanneer dit is opgehaald, voor de 'bijgewerkt op'-tekst en het ververs-ritme
    primary key (product_id, rank)
);

create table if not exists pokemon_interest (   -- Wikipedia-bezoekers per Pokémon (context, nog niet in de berekening)
    dex_id int not null, date date not null, views int,
    primary key (dex_id, date)
);

-- Trackrecord
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
           lp.price, f.p_up, f.signal
    from products p
    left join sets st on st.set_id = p.set_id
    left join lateral (
        select price from prices pr
        where pr.product_id = p.product_id and pr.grade_key = 'raw'
        order by date desc limit 1) lp on true
    left join forecasts f on f.product_id = p.product_id and f.horizon_days = 30 and f.threshold_pct = 10;

drop view if exists v_collection;
create view v_collection with (security_invoker = on) as
    select c.id, c.product_id, c.quantity, c.condition, c.grade_company, c.grade,
           c.purchase_price, c.purchase_date,
           p.kind, p.name, p.set_name, p.number, p.rarity, p.image,
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
           coalesce(sum(c.quantity * c.purchase_price) filter (where c.purchase_date <= d::date), 0),
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

do $$
declare t text;
begin
    foreach t in array array['sets','products','prices','forecasts','pokemon_interest','trackrecord_stats','trackrecord_signals','offers'] loop
        execute format('drop policy if exists "public read" on %I', t);
        execute format('create policy "public read" on %I for select to anon, authenticated using (true)', t);
    end loop;
    foreach t in array array['collection','alerts','user_settings','push_subscriptions','watch_folders','watch_items'] loop
        execute format('drop policy if exists "own rows" on %I', t);
        execute format('create policy "own rows" on %I for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid())', t);
    end loop;
end $$;

grant select on sets, products, prices, forecasts, pokemon_interest, trackrecord_stats, trackrecord_signals, offers to anon, authenticated;
grant select on v_forecasts, v_search to anon, authenticated;
grant select on v_collection to authenticated;
grant select on v_watchlist to authenticated;
grant select on latest_prices to service_role;
grant execute on function portfolio_series(int) to authenticated;
grant select, insert, update, delete on collection, alerts, user_settings, push_subscriptions, watch_folders, watch_items, watch_folder_items to authenticated;

drop policy if exists "own rows" on watch_folder_items;
create policy "own rows" on watch_folder_items for all to authenticated
    using (exists (select 1 from watch_folders f where f.id = folder_id and f.user_id = auth.uid()))
    with check (exists (select 1 from watch_folders f where f.id = folder_id and f.user_id = auth.uid())
                and exists (select 1 from watch_items i where i.id = item_id and i.user_id = auth.uid()));
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;

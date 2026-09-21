-- Plak dit hele bestand in Supabase → SQL Editor → Run. Veilig om opnieuw te draaien.

-- ===================== Gedeelde data (iedereen mag lezen) =====================
create table if not exists sets (
    set_id text primary key,
    name text,
    release_date date,
    card_total int
);

create table if not exists products (
    product_id text primary key,             -- kaarten: TCGdex-id (bijv. sv03.5-125); sealed: 'ppt:<id>'
    kind text not null default 'card' check (kind in ('card', 'sealed')),
    name text not null,
    set_id text, set_name text, number text, set_total int,
    rarity text, image text, category text, product_type text,
    dex_id int, regulation_mark text, legal_standard boolean,
    ppt_id text,                              -- id bij PokemonPriceTracker (tcgPlayerId)
    printings int, newer_printing boolean,    -- context voor herdrukken (nog niet in de berekening)
    updated_at timestamptz default now()
);
create index if not exists products_name_idx on products (lower(name));
create index if not exists products_number_idx on products (number);
create index if not exists products_ppt_idx on products (ppt_id);

create table if not exists prices (
    product_id text not null references products(product_id) on delete cascade,
    date date not null,
    source text not null default 'tcgdex',    -- tcgdex | ppt | ppt_hist
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
    p_up numeric, p_down numeric, exp_change numeric, score numeric, sigma numeric,
    signal text, mode text, confidence text, n int,
    updated date, computed_on date,
    primary key (product_id, horizon_days, threshold_pct)
);
create index if not exists forecasts_lookup on forecasts (horizon_days, threshold_pct, score desc);

create table if not exists pokemon_interest (   -- Wikipedia-bezoekers per Pokémon (context, nog niet in de berekening)
    dex_id int not null, date date not null, views int,
    primary key (dex_id, date)
);

-- Trackrecord
create table if not exists forecast_history (
    product_id text not null references products(product_id) on delete cascade,
    date date not null,
    p_up numeric, price numeric, signal text,
    resolved boolean not null default false,
    primary key (product_id, date)
);
create table if not exists trackrecord_stats (
    source text not null,                     -- live | backtest
    bucket text not null,                     -- 0-20 | 20-40 | 40-60 | 60-80 | 80-100 | all | koop
    n int not null default 0, hits int not null default 0, sum_p numeric not null default 0,
    primary key (source, bucket)
);
create table if not exists trackrecord_signals (
    id bigserial primary key,
    product_id text, name text, signal_date date, p_up numeric,
    change numeric, hit boolean, resolved_on date
);

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
create or replace view v_forecasts with (security_invoker = on) as
    select f.*, p.kind, p.name, p.set_name, p.number, p.rarity, p.image, p.dex_id
    from forecasts f join products p using (product_id);

create or replace view v_search with (security_invoker = on) as
    select p.product_id, p.kind, p.name, p.set_name, p.number, p.set_total, p.rarity, p.image,
           lp.price, f.p_up, f.signal
    from products p
    left join lateral (
        select price from prices pr
        where pr.product_id = p.product_id and pr.grade_key = 'raw'
        order by date desc limit 1) lp on true
    left join forecasts f on f.product_id = p.product_id and f.horizon_days = 30 and f.threshold_pct = 10;

create or replace view v_collection with (security_invoker = on) as
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

create or replace view latest_prices with (security_invoker = on) as
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

-- ===================== Beveiliging =====================
alter table sets enable row level security;
alter table products enable row level security;
alter table prices enable row level security;
alter table forecasts enable row level security;
alter table pokemon_interest enable row level security;
alter table forecast_history enable row level security;
alter table trackrecord_stats enable row level security;
alter table trackrecord_signals enable row level security;
alter table collection enable row level security;
alter table alerts enable row level security;
alter table user_settings enable row level security;
alter table push_subscriptions enable row level security;

do $$
declare t text;
begin
    foreach t in array array['sets','products','prices','forecasts','pokemon_interest','trackrecord_stats','trackrecord_signals'] loop
        execute format('drop policy if exists "public read" on %I', t);
        execute format('create policy "public read" on %I for select to anon, authenticated using (true)', t);
    end loop;
    foreach t in array array['collection','alerts','user_settings','push_subscriptions'] loop
        execute format('drop policy if exists "own rows" on %I', t);
        execute format('create policy "own rows" on %I for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid())', t);
    end loop;
end $$;

grant select on sets, products, prices, forecasts, pokemon_interest, trackrecord_stats, trackrecord_signals to anon, authenticated;
grant select on v_forecasts, v_search to anon, authenticated;
grant select on v_collection to authenticated;
grant select on latest_prices to service_role;
grant execute on function portfolio_series(int) to authenticated;
grant select, insert, update, delete on collection, alerts, user_settings, push_subscriptions to authenticated;
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;

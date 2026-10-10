# Backtest gestage stijgers

Kaarten met prijs >= 5 euro: 4585
- dekking ('raw', 'tcgdex'): 300 kaarten, dagen mediaan 20, max 20, vroegste 2026-09-21
- dekking ('nm', 'pkmnprices'): 266 kaarten, dagen mediaan 57, max 83, vroegste 2026-06-11
- dekking ('PSA-10', 'pkmnprices_ebay'): 65 kaarten, dagen mediaan 17, max 38, vroegste 2021-04-28
- dekking ('CGC-10', 'pkmnprices_ebay'): 60 kaarten, dagen mediaan 8, max 20, vroegste 2024-03-09
- dekking ('CGC-10-Pristine', 'pkmnprices_ebay'): 32 kaarten, dagen mediaan 2, max 8, vroegste 2024-02-18
- dekking ('BGS-10', 'pkmnprices_ebay'): 11 kaarten, dagen mediaan 5, max 17, vroegste 2021-05-29
- dekking ('us', 'tcgplayer'): 7 kaarten, dagen mediaan 103, max 107, vroegste 2026-04-13
- dekking ('BGS-10-Black_Label', 'pkmnprices_ebay'): 4 kaarten, dagen mediaan 3, max 4, vroegste 2022-12-19
Reeksen: 4003; dagen per kaart mediaan 57, max 85; vroegste datum 2026-06-11, laatste 2026-10-10
Meetmomenten: 11505 (elke 14 dagen per kaart, met 45 dagen verleden)

## Alle kaarten (vergelijkingsbasis): 11505 momenten, 2623 kaarten
- na 14 dagen (n=10742): mediaan +0.0%, gemiddeld +83.5%, >= +10%: 26%, >= +25%: 19%, verlies > 10%: 16%
- na 30 dagen (n=11028): mediaan +0.0%, gemiddeld +59.3%, >= +10%: 30%, >= +25%: 22%, verlies > 10%: 22%

## Gestage stijgers (>= +2%/maand, R2 >= 0.6, geen piek > 25% in 14 d, laatste maand -5..+15%): 123 momenten, 102 kaarten
- na 14 dagen (n=121): mediaan -0.2%, gemiddeld +4.0%, >= +10%: 7%, >= +25%: 5%, verlies > 10%: 24%
- na 30 dagen (n=120): mediaan -1.3%, gemiddeld +81.3%, >= +10%: 12%, >= +25%: 7%, verlies > 10%: 30%

## Sterke gestage stijgers (>= +4%/maand, R2 >= 0.75): 58 momenten, 55 kaarten
- na 14 dagen (n=58): mediaan -0.3%, gemiddeld +7.6%, >= +10%: 10%, >= +25%: 7%, verlies > 10%: 33%
- na 30 dagen (n=57): mediaan -3.8%, gemiddeld -1.3%, >= +10%: 12%, >= +25%: 5%, verlies > 10%: 35%

## Snelle stijgers (laatste maand >= +25%): 2673 momenten, 1488 kaarten
- na 14 dagen (n=2585): mediaan +0.0%, gemiddeld +30.4%, >= +10%: 17%, >= +25%: 13%, verlies > 10%: 27%
- na 30 dagen (n=2586): mediaan +0.0%, gemiddeld +26.1%, >= +10%: 21%, >= +25%: 15%, verlies > 10%: 33%

## Gestage dalers (<= -2%/maand, R2 >= 0.6): 1550 momenten, 1126 kaarten
- na 14 dagen (n=1482): mediaan +9.1%, gemiddeld +141.4%, >= +10%: 49%, >= +25%: 41%, verlies > 10%: 5%
- na 30 dagen (n=1421): mediaan +10.7%, gemiddeld +154.3%, >= +10%: 50%, >= +25%: 42%, verlies > 10%: 8%

## Gestage stijgers, prijs 5-20 euro: 58 momenten, 49 kaarten
- na 14 dagen (n=57): mediaan -0.3%, gemiddeld +0.5%, >= +10%: 7%, >= +25%: 4%, verlies > 10%: 28%
- na 30 dagen (n=57): mediaan -0.7%, gemiddeld +0.8%, >= +10%: 12%, >= +25%: 4%, verlies > 10%: 26%

## Gestage stijgers, prijs 20-75 euro: 42 momenten, 33 kaarten
- na 14 dagen (n=42): mediaan +0.0%, gemiddeld +13.1%, >= +10%: 10%, >= +25%: 7%, verlies > 10%: 21%
- na 30 dagen (n=40): mediaan -0.4%, gemiddeld -3.7%, >= +10%: 10%, >= +25%: 5%, verlies > 10%: 35%

## Gestage stijgers, prijs 75-... euro: 17 momenten, 15 kaarten
- na 14 dagen: te weinig gegevens (16)
- na 30 dagen: te weinig gegevens (17)


## Gestage stijgers nu (laatste 45 dagen, prijs >= 10 euro): 88

| kaart | set | nr | prijs | stijging/maand | rechtlijnigheid |
|---|---|---|---|---|---|
| Raikou & Suicune LEGEND | Unleashed | 93 | 79.26 | +517.6% | 0.93 |
| Charizard ex | FireRed & LeafGreen | 105 | 356.96 | +464.0% | 0.83 |
| Marill | McDonald's Collection 2015 | 10 | 11.42 | +311.4% | 0.90 |
| Dwebble | McDonald's Collection 2012 | 3 | 23.83 | +243.7% | 0.96 |
| Magneton | Skyridge | H19 | 10.48 | +249.1% | 0.93 |
| Lugia | Secret Wonders | 14 | 50.75 | +184.2% | 0.76 |
| Kabutops | Legend Maker | 7 | 12.86 | +110.0% | 0.91 |
| Deoxys | Call of Legends | SL1 | 43.46 | +54.6% | 0.68 |
| Dialga | Call of Legends | SL2 | 34.91 | +43.0% | 0.81 |
| Bellossom | Aquapolis | 5 | 38.96 | +43.4% | 0.73 |
| Lugia LEGEND | HeartGold SoulSilver | 114 | 64.13 | +27.8% | 0.74 |
| Pikachu | POP Series 6 | 9 | 80.65 | +21.8% | 0.89 |
| Jirachi ex | Crystal Guardians | 94 | 180.64 | +24.5% | 0.74 |
| Dragonite | Legends Awakened | 2 | 131.19 | +26.9% | 0.67 |
| Ampharos EX | Ancient Origins | 27 | 14.81 | +23.2% | 0.75 |
| Palkia GX | Forbidden Light | 119 | 16.95 | +19.3% | 0.80 |
| Zeraora V | Chilling Reign | 166 | 68.05 | +16.4% | 0.86 |
| Tapu Lele GX | Guardians Rising | 155 | 13.25 | +18.4% | 0.75 |
| Lugia BREAK | Fates Collide | 79 | 22.65 | +15.3% | 0.88 |
| Kingdra | Legends Awakened | 7 | 12.30 | +19.7% | 0.65 |
| Lillie | Sun & Moon | 147 | 32.19 | +17.4% | 0.71 |
| Lost Blender | Lost Thunder | 233 | 17.66 | +15.4% | 0.80 |
| Delcatty | Ruby & Sapphire | 5 | 12.87 | +18.0% | 0.66 |
| Raichu | Base Set 2 | 16 | 29.19 | +16.6% | 0.71 |
| Team Aqua's Kyogre EX | Double Crisis | 6 | 352.53 | +15.6% | 0.74 |
| Galarian Rapidash V | Chilling Reign | 168 | 55.24 | +16.0% | 0.66 |
| Aroma Lady | Evolving Skies | 199 | 12.57 | +16.4% | 0.64 |
| Mimikyu | SM Black Star Promos | SM29 | 14.38 | +14.5% | 0.72 |
| Mewtwo ex | Ruby & Sapphire | 101 | 139.77 | +15.9% | 0.65 |
| Mega Meganium ex | Ascended Heroes | 272 | 70.44 | +12.6% | 0.79 |
| Salamence | Dragon | 10 | 54.88 | +14.4% | 0.69 |
| Shining Arceus | Shining Legends | 57 | 49.59 | +13.0% | 0.75 |
| Reshiram & Zekrom GX | Cosmic Eclipse | 259 | 180.51 | +15.7% | 0.61 |
| Typhlosion ex | Sandstorm | 99 | 105.62 | +10.2% | 0.90 |
| Growlithe | Legendary Treasures | RC4 | 19.95 | +13.1% | 0.71 |
| Vanilluxe | White Flare | 113 | 35.86 | +13.1% | 0.70 |
| Slowpoke & Psyduck GX | Unified Minds | 218 | 54.34 | +13.9% | 0.66 |
| Scrafty | White Flare | 139 | 22.00 | +13.9% | 0.65 |
| Pikachu V-UNION | SWSH Black Star Promos | SWSH142 | 10.02 | +13.7% | 0.66 |
| Shaymin LV.X | Platinum | 127 | 37.34 | +13.6% | 0.67 |
| Arbok | Expedition Base Set | 3 | 116.72 | +13.9% | 0.65 |
| Scolipede | Black Bolt | 134 | 30.33 | +13.6% | 0.62 |
| Charizard GX | Burning Shadows | 20 | 18.26 | +13.0% | 0.62 |
| Scizor ex | Unseen Forces | 108 | 275.67 | +10.3% | 0.76 |
| Emboar | White Flare | 098 | 34.97 | +11.1% | 0.71 |
| Mega Sableye & Tyranitar GX | Unified Minds | 226 | 357.50 | +10.7% | 0.73 |
| Meganium ex | Unseen Forces | 106 | 59.49 | +12.7% | 0.61 |
| Zweilous | White Flare | 147 | 12.27 | +11.4% | 0.66 |
| Giratina EX | Ancient Origins | 57 | 15.00 | +11.8% | 0.62 |
| Gouging Fire ex | Temporal Forces | 204 | 38.63 | +8.4% | 0.86 |
| Charizard ex | Obsidian Flames | 228 | 26.92 | +11.7% | 0.62 |
| Mega Lopunny & Jigglypuff GX | Cosmic Eclipse | 225 | 73.84 | +9.8% | 0.73 |
| Pikachu | SM Black Star Promos | SM81 | 34.65 | +11.5% | 0.62 |
| Darkrai | XY Black Star Promos | XY22 | 32.37 | +11.1% | 0.60 |
| Chansey | Neo Destiny | 31 | 12.98 | +8.6% | 0.77 |
| Rayquaza | Dragons Exalted | 128 | 38.75 | +10.9% | 0.61 |
| Yanma | Neo Discovery | 36 | 29.69 | +10.0% | 0.65 |
| M Tyranitar EX | Ancient Origins | 43 | 39.02 | +8.6% | 0.74 |
| Altaria ex δ | Dragon Frontiers | 90 | 116.46 | +8.1% | 0.71 |
| Charizard EX | XY Black Star Promos | XY29 | 71.82 | +7.1% | 0.78 |

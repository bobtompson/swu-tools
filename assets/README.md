# SWU Logo Assets

Star Wars: Unlimited logo images pulled from the official media kit
(<https://starwarsunlimited.com/media-kit>), served from `cdn.starwarsunlimited.com`.

**License:** © & ™ Lucasfilm Ltd. / © Fantasy Flight Publishing, Inc. These are official
brand assets distributed via the media kit for community/press use under FFG's Marketing
Materials Policy. Not open-licensed — use accordingly (non-commercial fan tooling).

## `set-logos/` — per-set / product logos (transparent PNG)

| File | Set | Code |
|------|-----|------|
| `Spark_of_Rebellion.png` | Spark of Rebellion | SOR |
| `Shadows_of_the_Galaxy.png` | Shadows of the Galaxy | SHD |
| `Twilight_of_the_Republic.png` | Twilight of the Republic | TWI |
| `Jump_to_Lightspeed.png` | Jump to Lightspeed | JTL |
| `Legends_of_the_Force.png` | Legends of the Force | LOF |
| `Secrets_of_Power.png` | Secrets of Power | SEC |
| `A_Lawless_Time.png` | A Lawless Time | LAW |
| `Ashes_of_the_Empire.png` | Ashes of the Empire | ASH |
| `Intro_Battle_Hoth.png` | Intro Battle: Hoth | IBH |

SOR's logo is the inline page image (`spark_of_rebellion_Logo_*.png`), not a download zip.

## `set-colors/` — per-set signature colors

Each set has an official signature color shown on its media-kit page as a solid swatch image
(`SWH_Color_SWH_NN_*.png`). The swatch PNGs are saved here; the sampled hex values are in
[`set-colors.json`](set-colors.json):

| Set | Code | Hex |
|-----|------|-----|
| Spark of Rebellion | SOR | `#e10600` |
| Shadows of the Galaxy | SHD | `#3b3fb6` |
| Twilight of the Republic | TWI | `#7c2529` |
| Jump to Lightspeed | JTL | `#f2a900` |
| Legends of the Force | LOF | `#00a3e0` |
| Secrets of Power | SEC | `#68177f` |
| A Lawless Time | LAW | `#ff6900` |
| Ashes of the Empire | ASH | `#425563` |

Intro Battle: Hoth (IBH) has no set color.

## `logo-cutouts/` — unofficial cutouts (placeholder quality)

Logos cropped out of a cardgamer.com blog image
(`swu-2027-timeline-1024x576.jpg`, May 2026) — **not** media-kit assets: low-res,
navy starfield background baked in (not transparent). Placeholders until the media
kit ships the real logos, at which point these should be replaced.

| File | Product |
|------|---------|
| `Icons_2027_Edition.png` | Icons 2027 Edition (IC27, releases 11/20/26) |
| `Homeworlds.png` | Homeworlds (main set after ASH, Oct 2026, code TBA) |
| `Twin_Suns_Format.png` | Twin Suns format logo (not a set) |

## `logos/` — game + competitive-play logos

- `SWH_Logo_Black.png`, `SWH_Logo_White.png` — the Star Wars: Unlimited game logo.
- `season-1-competitive/` — Season 1 organized-play tier logos (Championship, Planetary,
  Regional, Sector). Not set logos, included for completeness.

## Re-fetching

Logos are downloaded from `https://cdn.starwarsunlimited.com//<Name>_Logo_<hash>.zip` (note the
double slash — it is part of the S3 key). Requires a browser `User-Agent`. The asset list comes
from `https://admin.starwarsunlimited.com/api/media-kit?populate=deep,10` (Strapi CMS).

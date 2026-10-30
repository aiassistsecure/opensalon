# webui — the salon-facing interface

Server-rendered Django templates with a hand-rolled CSS design system
(`static/webui/webui.css`). No JS framework, no build step. This app is
owned by the UI track, separately from the backend lanes: it never
edits other apps' models or migrations — it only reads them.

## Branding

The shell is branded BY THE SALON. The salon's name comes from its
`Salon` record; theme colours are CSS custom properties (`--salon-*`)
fed by `webui.context_processors.salon_context`, so a salon's own
branding drops in without template changes. OpenSalon appears only as
a small "powered by" note.

## Design system

`static/webui/webui.css` is a token-driven design system ("Botanical
Glamour"), documented at the top of the file. Salons override only the
`--salon-*` tokens; components consume semantic tokens (surfaces,
hairlines, accent, elevation, radius and type scales). Colour is
information, twice over:

- **Category palette** — each service category gets a colourway from
  `views.CATEGORY_PALETTE` in the salon's own category order; day book
  blocks wear it as their wash (`--wash`/`--ink` inline).
- **Status palette** — booked (harbour blue), confirmed (leaf green),
  arrived/`checked_in` (gold), in service (teal), done (grey-sage),
  no-show (terracotta), cancelled (dashed stone). Breaks are a
  separate hatched warm-stone treatment: gold flag = paid, grey =
  unpaid.
- **Staff tints** — each day book column header carries a soft
  signature tint + accent monogram, by column position.

Every interactive element has hover, focus-visible (gold ring) and
active states; money and times use tabular numerals; no form control
ships with default browser styling.

## Day book appointment-block contract

`webui.views.blocks_for_day(salon, day)` returns a list of dicts:

| key            | type          | notes                                  |
|----------------|---------------|----------------------------------------|
| `staff_id`     | int           | `StaffMember.pk` the block sits under  |
| `client_name`  | str           |                                        |
| `service_name` | str           |                                        |
| `start`/`end`  | datetime.time | salon-local, end after start           |
| `status`       | str           | booked, confirmed, checked_in, in_service, completed, no_show, cancelled |
| `note`         | str           | optional appointment-only note         |
| `category`     | str           | optional category name (shown on the block) |
| `category_id`  | int           | optional `ServiceCategory.pk` (colourway + category filter) |

The bookings lane (Lane 3) feeds this from real `Appointment` rows;
positioning math and the block template consume only this shape, so
no template changes are needed when it lands. Until then the function
returns `[]` and the day book shows its (intentional) empty state.
Roster shading already reads real `RosterPattern` rows today: rostered
time renders as *Available* (sage wash), non-rostered columns render
off-duty — the front desk reads bookable gaps at a glance.

## Day book breaks contract

`webui.views.breaks_for_day(salon, day)` returns a list of dicts:

| key            | type          | notes                                  |
|----------------|---------------|----------------------------------------|
| `staff_id`     | int           | `StaffMember.pk`                         |
| `start`/`end`  | datetime.time | salon-local, end after start           |
| `paid`         | bool          | paid vs unpaid — payroll-relevant, always rendered |
| `label`        | str           | optional, e.g. "Lunch"                 |

A break removes its span from availability. Breaks need a backend
home (blocked-time records in the bookings lane); until that model
lands the function returns `[]`.

## Day book controls & filters

All GET-driven and bookmarkable: `date` (prev/next/today, week strip,
jump-to-date picker), `off` (comma-separated hidden staff ids — the
team chips toggle them), `status` (one status), `cat`
(`ServiceCategory.pk`). Price book: `q` search + `cat` category.
Clients: `q` search + `opt` (`sms` | `email` | `notes`).

## Pages

- `/` Day Book — date control + week strip, filters, one column per
  active staff member, hour grid 8:00–20:00, availability bands,
  appointment blocks, break blocks.
- `/clients/` — searchable client list, opt-in filters, SMS/email
  opt-in badges, record-note indicator.
- `/price-book/` — search + category filter, services grouped by
  category, duration, one price column per staff level.
- `/team/`, `/products/`, `/insights/` — placeholders for their lanes.

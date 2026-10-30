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

## Day book appointment-block contract

`webui.views.blocks_for_day(salon, day)` returns a list of dicts:

| key            | type          | notes                                  |
|----------------|---------------|----------------------------------------|
| `staff_id`     | int           | `StaffMember.pk` the block sits under  |
| `client_name`  | str           |                                        |
| `service_name` | str           |                                        |
| `start`/`end`  | datetime.time | salon-local, end after start           |
| `status`       | str           | booked, confirmed, checked_in, completed, no_show, cancelled |
| `note`         | str           | optional appointment-only note         |

The bookings lane (Lane 3) feeds this from real `Appointment` rows;
positioning math and the block template consume only this shape, so
no template changes are needed when it lands. Until then the function
returns `[]` and the day book shows its (intentional) empty state.
Roster shading already reads real `RosterPattern` rows today.

## Pages

- `/` Day Book — date navigation, one column per active staff member,
  hour grid 8:00–20:00, roster bands, appointment blocks.
- `/clients/` — searchable client list, SMS/email opt-in badges,
  record-note indicator.
- `/price-book/` — services grouped by category, duration, one price
  column per staff level.
- `/team/`, `/products/`, `/insights/` — placeholders for their lanes.

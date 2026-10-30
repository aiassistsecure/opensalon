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
the sidebar wordmark and a small "powered by" note.

## App shell

The interface lives in an app frame, not a web page: a deep-forest
left sidebar (salon medallion + name + "Front Desk", vertical icon nav
with the active item as a gold pill, the signed-in user chip pinned to
the bottom, the OPENSALON wordmark), an app bar (global client
search, today's date, gold New Appointment) and the warm-creme
content surface on a dark backdrop. Every page — day book, price
book, clients, placeholders, breakdown, forms — sits inside the same
frame. The nav's last item is **Reports** (the insights lane's future
home).

## Design system

`static/webui/webui.css` is a token-driven design system, documented
at the top of the file. Salons override only the `--salon-*` tokens;
components consume semantic tokens (surfaces, hairlines, accent,
elevation, radius and type scales). Colour is information, carried by
meaning — never decoration:

- **Category colourways** — `views.CATEGORY_COLORWAYS` maps category
  name fragments to saturated gradients (color = deep teal, highlight
  = berry, cut/hair = forest, extensions = amber, texture = plum,
  treatments = sage, nails = rose, consultation = harbour, wax/brow/
  lash = violet; unmapped categories rotate through the same family,
  and a category-id memo keeps a category's colour stable all day).
  Day book blocks are filled with the gradient in white type; the
  price book group headings wear the same colourway as a dot.
- **Status glyphs** — the block's top line shows its state: Booked ○,
  Confirmed ✓, Arrived ◉ (with a gold ring on the block), In service
  ●, Completed ✓ (the block softens), No-show ✕, Cancelled — (dashed,
  transparent). Breaks are a separate hatched warm-stone treatment
  with a PAID / UNPAID flag pill.
- **Staff signature bands** — each day book column header is a
  gradient band in the stylist's signature colour (position-assigned
  from `views.STAFF_BANDS`) showing their level and how full the day
  is: **booked-% is computed** from that day's appointment minutes
  against rostered minutes (Full at ≥ 100%, Openings at 0%) — never
  invented.

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
| `status`       | str           | booked, confirmed, arrived, in_service, completed, no_show, cancelled |
| `note`         | str           | optional appointment-only note         |
| `price`        | Decimal/None  | optional — the stylist's level price for the service, rendered bottom-right on the block |
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

## Action bar (day book)

The bar under the grid acts on the **selected** appointment: the
first click on a block selects it (the chip fills with client, time
and service, and Pay / Add Service / Notes / Copy arm themselves);
clicking the selected block again opens its breakdown. Check In and
Confirm post to `/appointment/<id>/action/<action>/`, which goes
through the `set_appointment_status` contract below and lands on the
breakdown's honest pending state until the bookings lane acts on it.
A gold now-line marks the current time on today's view.

## The click model (day book interactions)

Implemented in `webui/interactions.py` + `webui/forms.py`, styled
entirely from the design system's components:

- **Click an appointment block** → its **breakdown**
  (`/appointment/<id>/`): the visit's services as priced line items
  with a running total, appointment notes vs client record notes as
  the two distinct kinds they are, and Copy / Add service / Pay
  actions. A *visit* is the contiguous chain of same-client,
  same-stylist appointments where each starts when the previous ends
  (the bookings model carries one service per appointment). Prices
  are read live from the price book at the stylist's level — never
  stored on the appointment, never typed in at the desk.
- **Add service** (`/appointment/<id>/add-service/`) books the chosen
  service as the next appointment in the visit's chain.
- **Close out / Pay** (`/appointment/<id>/close-out/`) shows the
  visit total and hands the visit to checkout (Lane 4) via
  `close_out_visit` — until Lane 4 lands it takes no payment and
  says so. No fake success state exists anywhere in this app.
- **Click empty column space** → the **booking form**
  (`/appointment/new/`), prefilled with that stylist and the clicked
  time (15-minute snap). Client pick is a name search backed by the
  real client book; services carry duration + price from the price
  book; the note field is an appointment-only note.
- **Copy** — the day book toolbar's ⧉ Copy toggle arms copy mode:
  click a block to pick the visit up, click any slot (any stylist,
  any time on the visible day) to open the copy form targeted there;
  Esc disarms. Blocks and the breakdown also carry explicit Copy
  actions (`/appointment/copy/?source=<id>`) — copying a visit copies
  its whole chain, keeping relative timing.
- **Breaks** — every column head carries a ＋ Break action (and the
  booking form's sibling `/break/new/`): stylist, date, start,
  length, label, and the **paid** flag — payroll data, captured
  explicitly, rendered on the break block always.

### Interaction contracts (webui/interactions.py)

All persistence goes through these functions; each imports the
bookings models lazily, so while the bookings lane is not on main
they resolve to "not wired" and the pages say plainly that nothing
was saved/booked/copied/paid:

| function | returns |
|----------|---------|
| `breakdown_for_appointment(salon, id)` | visit dict (shape in its docstring) or None |
| `create_appointment(salon, *, client, staff, service, day, start, note)` | new appointment id or None |
| `copy_appointment(salon, id, *, staff, day, start)` | first copy's id or None |
| `add_service_to_visit(salon, id, service)` | bool |
| `create_break(salon, *, staff, day, start, minutes, paid, label)` | bool — awaits the bookings lane's blocked-time/break model |
| `close_out_visit(salon, id)` | checkout handoff dict or None (Lane 4) |
| `set_appointment_status(salon, id, action)` | bool — action-bar contract: `checkin` (booked/confirmed → arrived), `confirm` (booked → confirmed) |

`blocks_for_day` already reads real `Appointment` rows the moment
the bookings app is installed (see `_block_from_appointment`), and
statuses use the bookings model's own vocabulary (`arrived`, not
`checked_in`).

## Pages

- `/` Day Book — date control + week strip, filters, copy mode, one
  column per active staff member, hour grid 8:00–20:00, availability
  bands, appointment blocks, break blocks, staff signature bands
  with booked-%, the selection action bar.
- `/appointment/<id>/` breakdown · `/appointment/<id>/add-service/` ·
  `/appointment/<id>/close-out/` · `/appointment/<id>/action/<action>/`
  action-bar POSTs · `/appointment/new/` booking form ·
  `/appointment/copy/` copy form · `/break/new/` break form.
- `/clients/` — searchable client list, opt-in filters, SMS/email
  opt-in badges, record-note indicator.
- `/price-book/` — search + category filter, services grouped by
  category (colourway dot), duration, one price column per staff level.
- `/team/`, `/products/`, `/insights/` — placeholders for their lanes
  (the last is labelled **Reports** in the nav).

# Online booking stores nothing of its own: a booking is a
# bookings.Appointment, availability comes from team roster patterns
# via bookings.availability, and the per-staff online-booking toggle
# lives on team.StaffMember. This module exists only so Django
# registers the app.

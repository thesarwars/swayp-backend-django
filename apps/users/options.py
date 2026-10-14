"""Choice lists for the sign-up and settings forms (web §4).

The fields stay free text on the way in, so nothing a client already sends
is refused; these lists are what a form should offer, with a stable
``value`` to send and a ``label`` to show. Edit them here, in one place.

Defaults, to be confirmed against the design: the register example uses
"11-50", which matches the sizes below.
"""

INDUSTRIES = (
    ("construction", "Construction"),
    ("real_estate", "Real estate"),
    ("professional_services", "Professional services"),
    ("healthcare", "Healthcare"),
    ("retail", "Retail"),
    ("restaurants_hospitality", "Restaurants & hospitality"),
    ("manufacturing", "Manufacturing"),
    ("technology", "Technology"),
    ("transportation_logistics", "Transportation & logistics"),
    ("nonprofit", "Nonprofit"),
    ("other", "Other"),
)

BUSINESS_SIZES = (
    ("1-10", "1–10 employees"),
    ("11-50", "11–50 employees"),
    ("51-200", "51–200 employees"),
    ("201-500", "201–500 employees"),
    ("500+", "500+ employees"),
)

BUSINESS_TYPES = (
    ("sole_proprietorship", "Sole proprietorship"),
    ("llc", "LLC"),
    ("s_corporation", "S corporation"),
    ("c_corporation", "C corporation"),
    ("partnership", "Partnership"),
    ("nonprofit", "Nonprofit"),
    ("other", "Other"),
)


def as_options(pairs):
    return [{"value": value, "label": label} for value, label in pairs]

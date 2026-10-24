"""Build app/acquisition/places.json, the built-in list of Indian places.

    python scripts/build_gazetteer.py

The list is the geocoder of last resort: when Nominatim and Photon both
refuse (a cloud host's shared IP address is often over their limits), a
question about a well-known place still works. Each entry is Nominatim's own
answer, fetched once here at its requested one request a second.
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.acquisition.location import best_match  # noqa: E402
from app.acquisition.web import request_json  # noqa: E402

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OUTPUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app", "acquisition", "places.json",
)

#: The places the workspace suggests, state and union-territory capitals, the
#: largest cities, and landscapes people ask about. A pair is (name, the text
#: to search for) where the name alone finds the wrong thing. The Sundarbans
#: are left out: Nominatim has no area for them, only a resort of that name.
PLACES = [
    "Pune", "Kochi", "Varanasi", "Gurugram", "Nagpur", "Hosur", "Chilika Lake", "Bhopal",
    "Delhi", "Mumbai", "Bengaluru", "Chennai", "Kolkata", "Hyderabad", "Ahmedabad",
    "Jaipur", "Lucknow", "Patna", "Bhubaneswar", "Guwahati", "Thiruvananthapuram",
    "Chandigarh", "Dehradun", "Shimla", "Srinagar", "Jammu", "Ranchi", "Raipur",
    "Gandhinagar", "Panaji", "Imphal", "Shillong", "Agartala", "Aizawl", "Kohima",
    "Itanagar", "Gangtok", "Puducherry", "Leh", "Port Blair", "Amaravati",
    "Surat", "Indore", "Visakhapatnam", "Coimbatore", "Madurai", "Mysuru", "Nashik",
    "Amritsar", "Kanpur", "Prayagraj", "Agra", "Udaipur", "Jodhpur", "Noida", "Thane",
    "Vijayawada", "Mangaluru", "Kozhikode", "Alappuzha", "Haridwar", "Rishikesh",
    "Wayanad", "Dal Lake", "Loktak Lake",
    "Vembanad Lake", ("Kaziranga", "Kaziranga National Park"),
    "Sambhar Lake", "Pulicat Lake", "Majuli",
]

#: Other names for the same places, English and Hindi.
ALIASES = {
    "bangalore": "Bengaluru", "bombay": "Mumbai", "calcutta": "Kolkata",
    "madras": "Chennai", "gurgaon": "Gurugram", "trivandrum": "Thiruvananthapuram",
    "allahabad": "Prayagraj", "mysore": "Mysuru", "cochin": "Kochi",
    "mangalore": "Mangaluru", "calicut": "Kozhikode", "new delhi": "Delhi",
    "benares": "Varanasi", "banaras": "Varanasi", "chilika": "Chilika Lake",
    "पुणे": "Pune", "कोच्चि": "Kochi", "वाराणसी": "Varanasi", "गुरुग्राम": "Gurugram",
    "नागपुर": "Nagpur", "होसुर": "Hosur", "चिल्का झील": "Chilika Lake", "भोपाल": "Bhopal",
    "दिल्ली": "Delhi", "नई दिल्ली": "Delhi", "मुंबई": "Mumbai", "बेंगलुरु": "Bengaluru",
    "चेन्नई": "Chennai", "कोलकाता": "Kolkata", "हैदराबाद": "Hyderabad",
    "अहमदाबाद": "Ahmedabad", "जयपुर": "Jaipur", "लखनऊ": "Lucknow", "पटना": "Patna",
    "भुवनेश्वर": "Bhubaneswar", "गुवाहाटी": "Guwahati", "चंडीगढ़": "Chandigarh",
    "देहरादून": "Dehradun", "शिमला": "Shimla", "श्रीनगर": "Srinagar", "रांची": "Ranchi",
    "रायपुर": "Raipur", "इंदौर": "Indore", "सूरत": "Surat", "आगरा": "Agra",
    "कानपुर": "Kanpur", "प्रयागराज": "Prayagraj", "हरिद्वार": "Haridwar",
}


def main() -> int:
    places = {}
    for entry in PLACES:
        name, search = entry if isinstance(entry, tuple) else (entry, entry)
        results = request_json(
            NOMINATIM,
            params={"q": f"{search}, India", "format": "jsonv2", "limit": 5, "accept-language": "en"},
            timeout=60,
        )
        time.sleep(1.1)
        if not results:
            print(f"not found: {name}")
            continue
        match = best_match(results)
        places[name.lower()] = {
            key: match[key]
            for key in ("category", "lat", "lon", "boundingbox", "display_name")
        }
        print(f"{name}: {match['display_name']}")

    for alias, name in ALIASES.items():
        if name.lower() in places:
            places[alias] = places[name.lower()]

    with open(OUTPUT, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(places, handle, ensure_ascii=False, indent=1, sort_keys=True)
        handle.write("\n")
    print(f"{len(places)} names written to {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

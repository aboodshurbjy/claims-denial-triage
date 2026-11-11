"""Seeded synthetic data generator.

Writes three deliberately messy source files plus an answer key:

    raw/claims_export.csv      practice-management claims export
    raw/member_roster.xlsx     monthly eligibility roster, one sheet per month
    raw/authorizations.json    prior-authorization feed
    truth/claims_truth.csv     which defect was injected into which claim
    truth/roster_truth.csv     which person each roster row really is
    manifest.json              seed, as-of date and row counts

Every person, identifier and claim is invented. The truth files are never
read by the pipeline; they exist so tests can check that the pipeline and
the rules find what was planted.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook

AS_OF = date(2025, 6, 30)
ROSTER_MONTHS = [(2025, m) for m in range(1, 7)]

# code -> (description, rate per unit, requires prior auth, max units per day)
SERVICES = {
    "H0031": ("Mental health assessment", 148.00, False, 1),
    "H0004": ("Behavioral health counseling, 15 min", 24.50, True, 8),
    "H2017": ("Psychosocial rehabilitation, 15 min", 16.75, True, 16),
    "H0036": ("Community psychiatric support, 15 min", 21.00, True, 12),
    "T1017": ("Targeted case management, 15 min", 19.25, False, 8),
    "90837": ("Psychotherapy, 60 min", 132.00, False, 1),
}
AUTH_CODES = [c for c, s in SERVICES.items() if s[2]]
OPEN_CODES = [c for c, s in SERVICES.items() if not s[2]]

FIRST_NAMES = [
    "William", "Robert", "Elizabeth", "Katherine", "Michael", "Jennifer", "Christopher",
    "Margaret", "Anthony", "Patricia", "Daniel", "Rebecca", "Joseph", "Samantha", "Benjamin",
    "Alexander", "Victoria", "Nicholas", "Stephanie", "Jonathan", "Gabriela", "Marcus",
    "Latoya", "Darnell", "Yolanda", "Terrence", "Monique", "Andre", "Carmen", "Rafael",
    "Lucia", "Hector", "Priya", "Arjun", "Mei", "Kenji", "Fatima", "Omar", "Ingrid",
    "Declan", "Sienna", "Malik", "Tanisha", "Wesley", "Brianna", "Curtis", "Noelle",
    "Xavier", "Imani", "Desmond",
]
NICKNAMES = {
    "William": "Bill", "Robert": "Bob", "Elizabeth": "Liz", "Katherine": "Kate",
    "Michael": "Mike", "Jennifer": "Jen", "Christopher": "Chris", "Margaret": "Peggy",
    "Anthony": "Tony", "Patricia": "Pat", "Daniel": "Dan", "Rebecca": "Becky",
    "Joseph": "Joe", "Samantha": "Sam", "Benjamin": "Ben", "Alexander": "Alex",
    "Victoria": "Vicky", "Nicholas": "Nick", "Stephanie": "Steph", "Jonathan": "Jon",
}
LAST_NAMES = [
    "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis", "Rodriguez", "Martinez",
    "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore",
    "Jackson", "Martin", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez",
    "Lewis", "Robinson", "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres",
    "Nguyen", "Hill", "Flores", "Green", "Adams", "Nelson", "Baker", "Rivera", "Campbell",
    "Mitchell", "Carter", "Garcia-Lopez", "Nguyen-Tran", "Smith-Jones", "Okafor-Bell",
    "De La Cruz", "Van Horn",
]
TWIN_FIRST_NAMES = [("Elena", "Tomas"), ("Naomi", "Victor"), ("Grace", "Dmitri")]
PLANS = ["BH Managed Care", "BH Fee-for-Service"]

PROVIDERS = [
    ("1900000014", "Lena Park, LCSW"),
    ("1900000022", "Marcus Bell, LPC"),
    ("1900000030", "Renee Castillo, LMFT"),
    ("1900000048", "Dev Anand, PsyD"),
    ("1900000055", "Joan Whitfield, LCSW"),
    ("1900000063", "Samuel Ortiz, LPC"),
    ("1900000071", "Hannah Greer, PMHNP"),
    ("1900000089", "Isaac Molina, LCSW"),
]


@dataclass
class Person:
    pid: int
    first: str
    last: str
    dob: date
    medicaid_id: str
    new_medicaid_id: str | None = None      # re-enrolled under a new ID
    new_id_from_month: int = 99
    months: set[int] = field(default_factory=lambda: set(range(len(ROSTER_MONTHS))))
    term_date: date | None = None           # coverage ends mid-month

    def id_in_month(self, month_index: int) -> str:
        if self.new_medicaid_id and month_index >= self.new_id_from_month:
            return self.new_medicaid_id
        return self.medicaid_id

    def covered(self, d: date) -> bool:
        index = next((i for i, (y, m) in enumerate(ROSTER_MONTHS) if (y, m) == (d.year, d.month)), None)
        if index is None or index not in self.months:
            return False
        return self.term_date is None or d <= self.term_date


@dataclass
class Auth:
    number: str
    pid: int
    code: str
    npi: str
    start: date
    end: date | None
    units: int
    status: str = "approved"


@dataclass
class ClaimRow:
    number: str
    first: str
    last: str
    dob: date
    medicaid_id: str
    npi: str
    code: str
    dos: date
    units: int
    auth_number: str
    created: date
    defect: str = "none"
    expected_rule: str = ""
    expected_status: str = "pass"

    @property
    def charge(self) -> float:
        return round(self.units * SERVICES[self.code][1], 2)


class Generator:
    def __init__(self, seed: int = 42, n_members: int = 140, n_clean_claims: int = 420):
        self.rng = random.Random(seed)
        self.seed = seed
        self.n_members = n_members
        self.n_clean_claims = n_clean_claims
        self.people: list[Person] = []
        self.auths: list[Auth] = []
        self.claims: list[ClaimRow] = []
        self.ids_in_use: set[str] = set()
        self.auth_numbers: set[str] = set()
        self.codes_taken: dict[int, set[str]] = {}
        self.service_keys: set[tuple[int, str, date]] = set()
        self.claim_seq = 0

    # ------------------------------------------------------------------ people

    def new_medicaid_id(self) -> str:
        while True:
            digits = f"{self.rng.randrange(10**9):09d}"
            lead = "0" if self.rng.random() < 0.2 else str(self.rng.randint(1, 9))
            candidate = lead + digits
            if candidate not in self.ids_in_use:
                self.ids_in_use.add(candidate)
                return candidate

    def random_dob(self) -> date:
        return date(1945, 1, 1) + timedelta(days=self.rng.randrange((date(2018, 12, 31) - date(1945, 1, 1)).days))

    def build_people(self) -> None:
        rng = self.rng
        pairs = [(f, l) for f in FIRST_NAMES for l in LAST_NAMES]
        rng.shuffle(pairs)
        for pid in range(self.n_members):
            first, last = pairs[pid]
            self.people.append(Person(pid, first, last, self.random_dob(), self.new_medicaid_id()))

        # twins: same last name and birth date, different first names and IDs
        for k, (a, b) in enumerate(TWIN_FIRST_NAMES):
            one, two = self.people[2 * k], self.people[2 * k + 1]
            one.first, two.first = a, b
            two.last, two.dob = one.last, one.dob
        # re-enrolled under a new Medicaid ID from April onward
        for p in self.people[6:11]:
            p.new_medicaid_id, p.new_id_from_month = self.new_medicaid_id(), 3
        # lost eligibility after April, a few terminated mid-month
        for k, p in enumerate(self.people[11:19]):
            p.months = {0, 1, 2, 3}
            if k < 3:
                p.term_date = date(2025, 4, 15)
        # one-month gap in May
        for p in self.people[19:23]:
            p.months = {0, 1, 2, 3, 5}
        # newly enrolled in March
        for p in self.people[23:33]:
            p.months = {2, 3, 4, 5}
        self.codes_taken = {p.pid: set() for p in self.people}

    # ------------------------------------------------------------------- auths

    def new_auth_number(self) -> str:
        while True:
            number = f"PA{self.rng.randrange(10**7):07d}"
            if number not in self.auth_numbers:
                self.auth_numbers.add(number)
                return number

    def add_auth(self, person: Person, code: str, start: date, end: date | None, units: int, status: str = "approved") -> Auth:
        auth = Auth(self.new_auth_number(), person.pid, code, self.rng.choice(PROVIDERS)[0], start, end, units, status)
        self.auths.append(auth)
        self.codes_taken[person.pid].add(code)
        return auth

    def build_standard_auths(self) -> None:
        rng = self.rng
        for person in self.people:
            for code in rng.sample(AUTH_CODES, rng.choice([1, 1, 2])):
                start = rng.choice([date(2025, 3, 15), date(2025, 4, 1)])
                end = None if rng.random() < 0.04 else start + timedelta(days=183)
                self.add_auth(person, code, start, end, rng.randrange(300, 601, 20))

    def standard_auths(self) -> list[Auth]:
        return [a for a in self.auths if a.status == "approved" and a.units >= 300]

    def person_with_free_code(self, pool: list[Person] | None = None) -> tuple[Person, str]:
        """A person and an auth-required code they hold no authorization for."""
        candidates = pool or self.fully_enrolled()
        while True:
            person = self.rng.choice(candidates)
            free = [c for c in AUTH_CODES if c not in self.codes_taken[person.pid]]
            if free:
                code = self.rng.choice(free)
                self.codes_taken[person.pid].add(code)
                return person, code

    def fully_enrolled(self) -> list[Person]:
        return [p for p in self.people if len(p.months) == len(ROSTER_MONTHS) and p.term_date is None]

    # ------------------------------------------------------------------ claims

    def random_date(self, lo: date, hi: date) -> date:
        return lo + timedelta(days=self.rng.randrange((hi - lo).days + 1))

    def free_dos(self, person: Person, code: str, lo: date, hi: date, must_be_covered: bool = True) -> date:
        for _ in range(500):
            dos = self.random_date(lo, hi)
            if (person.pid, code, dos) in self.service_keys:
                continue
            if must_be_covered and not person.covered(dos):
                continue
            return dos
        raise RuntimeError(f"no free date of service for person {person.pid} {code} {lo}..{hi}")

    def add_claim(self, person: Person, code: str, dos: date, units: int, auth_number: str = "",
                  npi: str | None = None, **overrides) -> ClaimRow:
        self.claim_seq += 1
        self.service_keys.add((person.pid, code, dos))
        month_index = next((i for i, (y, m) in enumerate(ROSTER_MONTHS) if (y, m) == (dos.year, dos.month)), 0)
        medicaid_id = person.id_in_month(month_index)
        if person.new_medicaid_id and self.rng.random() < 0.4:
            medicaid_id = person.medicaid_id  # billing system still holds the old ID
        row = ClaimRow(
            number=f"CLM-{self.claim_seq:06d}",
            first=person.first, last=person.last, dob=person.dob, medicaid_id=medicaid_id,
            npi=npi or self.rng.choice(PROVIDERS)[0], code=code, dos=dos, units=units,
            auth_number=auth_number,
            created=min(AS_OF, dos + timedelta(days=self.rng.randint(0, 4))),
        )
        for key, value in overrides.items():
            setattr(row, key, value)
        self.claims.append(row)
        return row

    def clean_units(self, code: str) -> int:
        return self.rng.randint(1, max(1, SERVICES[code][3] // 2))

    def build_clean_claims(self) -> None:
        rng = self.rng
        lo, hi = date(2025, 4, 20), date(2025, 6, 27)
        auths_by_person: dict[int, list[Auth]] = {}
        for auth in self.standard_auths():
            auths_by_person.setdefault(auth.pid, []).append(auth)
        made = 0
        while made < self.n_clean_claims:
            person = rng.choice(self.people)
            try:
                if rng.random() < 0.6:
                    auth = rng.choice(auths_by_person[person.pid])
                    dos = self.free_dos(person, auth.code, lo, hi)
                    self.add_claim(person, auth.code, dos, self.clean_units(auth.code), auth.number, auth.npi)
                else:
                    code = rng.choice(OPEN_CODES)
                    dos = self.free_dos(person, code, lo, hi)
                    self.add_claim(person, code, dos, self.clean_units(code))
            except RuntimeError:
                continue  # person has no coverage in the window
            made += 1

    def build_defect_claims(self) -> None:
        rng = self.rng
        recent = (date(2025, 4, 20), date(2025, 6, 27))
        enrolled = self.fully_enrolled()
        standard = [a for a in self.standard_auths() if self.people[a.pid] in enrolled]
        clean = [c for c in self.claims]
        by_number = {p.medicaid_id: p for p in self.people} | {
            p.new_medicaid_id: p for p in self.people if p.new_medicaid_id}

        def flag(row: ClaimRow, defect: str, rule: str, status: str) -> None:
            row.defect, row.expected_rule, row.expected_status = defect, rule, status

        # auth is on file but the number never made it onto the claim
        for auth in rng.sample(standard, 25):
            person = self.people[auth.pid]
            row = self.add_claim(person, auth.code, self.free_dos(person, auth.code, *recent),
                                 self.clean_units(auth.code), "", auth.npi)
            flag(row, "missing_auth_number", "auth_exists", "warn")

        # service needs an auth and none was ever requested
        for _ in range(15):
            person, code = self.person_with_free_code()
            row = self.add_claim(person, code, self.free_dos(person, code, *recent), self.clean_units(code))
            flag(row, "no_auth_on_file", "auth_exists", "fail")

        # auth number on the claim is not in the feed
        for auth in rng.sample(standard, 10):
            person = self.people[auth.pid]
            row = self.add_claim(person, auth.code, self.free_dos(person, auth.code, *recent),
                                 self.clean_units(auth.code), self.new_auth_number(), auth.npi)
            flag(row, "unknown_auth_number", "auth_exists", "fail")

        # auth was denied, or is still pending
        for status, count, expected in (("denied", 6, "fail"), ("pending", 4, "warn")):
            for _ in range(count):
                person, code = self.person_with_free_code()
                auth = self.add_auth(person, code, date(2025, 4, 1), date(2025, 9, 30), 120, status)
                row = self.add_claim(person, code, self.free_dos(person, code, *recent),
                                     self.clean_units(code), auth.number, auth.npi)
                flag(row, f"auth_{status}", "auth_exists", expected)

        # service delivered after the auth window closed
        for _ in range(18):
            person, code = self.person_with_free_code()
            auth = self.add_auth(person, code, date(2025, 1, 15), date(2025, 5, 15), 200)
            dos = self.free_dos(person, code, date(2025, 5, 18), date(2025, 6, 20))
            row = self.add_claim(person, code, dos, self.clean_units(code), auth.number, auth.npi)
            flag(row, "outside_auth_window", "service_inside_auth_window", "fail")

        # more units in one day than the code allows
        for auth in rng.sample(standard, 15):
            person = self.people[auth.pid]
            units = SERVICES[auth.code][3] + rng.randint(1, 6)
            row = self.add_claim(person, auth.code, self.free_dos(person, auth.code, *recent),
                                 units, auth.number, auth.npi)
            flag(row, "units_over_daily_cap", "units_under_cap", "fail")

        # small auth used up over five visits: two pass, one lands on the cap, two exceed it
        for _ in range(6):
            person, code = self.person_with_free_code()
            per_visit = SERVICES[code][3] // 2
            auth = self.add_auth(person, code, date(2025, 4, 1), date(2025, 9, 30), per_visit * 3)
            visits: list[date] = []
            while len(visits) < 5:
                dos = self.free_dos(person, code, *recent)
                if dos not in visits:
                    visits.append(dos)
            for position, dos in enumerate(sorted(visits)):
                row = self.add_claim(person, code, dos, per_visit, auth.number, auth.npi)
                if position >= 2:
                    flag(row, "auth_units_exhausted", "units_under_cap", "warn" if position == 2 else "fail")

        # same service billed twice under a new claim number
        for original in rng.sample(clean, 15):
            person = by_number[original.medicaid_id]
            row = self.add_claim(person, original.code, original.dos, original.units,
                                 original.auth_number, original.npi,
                                 created=min(AS_OF, original.created + timedelta(days=rng.randint(1, 3))))
            flag(row, "duplicate_claim", "duplicate_claim", "fail")

        # same service and day billed by a second clinician
        for original in rng.sample([c for c in clean if not c.auth_number], 6):
            person = by_number[original.medicaid_id]
            other_npi = rng.choice([npi for npi, _ in PROVIDERS if npi != original.npi])
            row = self.add_claim(person, original.code, original.dos, original.units, "", other_npi,
                                 created=min(AS_OF, original.created + timedelta(days=1)))
            flag(row, "possible_duplicate", "duplicate_claim", "warn")

        # past, or close to, the 90-day filing limit
        for count, lo, hi, defect, expected in (
            (14, date(2025, 2, 3), date(2025, 3, 28), "late_filing", "fail"),
            (10, date(2025, 4, 2), date(2025, 4, 16), "filing_deadline_near", "warn"),
        ):
            for _ in range(count):
                person, code = rng.choice(enrolled), rng.choice(OPEN_CODES)
                row = self.add_claim(person, code, self.free_dos(person, code, lo, hi), self.clean_units(code))
                flag(row, defect, "timely_filing", expected)

        # member was not eligible on the date of service
        for person in self.people[11:19]:
            for _ in range(2):
                code = rng.choice(OPEN_CODES)
                dos = self.free_dos(person, code, date(2025, 5, 2), date(2025, 6, 25), must_be_covered=False)
                flag(self.add_claim(person, code, dos, self.clean_units(code)),
                     "not_eligible", "eligibility_on_dos", "fail")
        for person in self.people[19:23]:
            code = rng.choice(OPEN_CODES)
            dos = self.free_dos(person, code, date(2025, 5, 2), date(2025, 5, 30), must_be_covered=False)
            flag(self.add_claim(person, code, dos, self.clean_units(code)),
                 "not_eligible", "eligibility_on_dos", "fail")

        # patient is not on the roster at all
        strangers = [("Quentin", "Abernathy"), ("Odessa", "Kowalczyk"), ("Leopold", "Brandvold"),
                     ("Marisol", "Etxeberria"), ("Thaddeus", "Okonkwo"), ("Winifred", "Zamora")]
        for index, (first, last) in enumerate(strangers):
            stranger = Person(10_000 + index, first, last, self.random_dob(), self.new_medicaid_id())
            code = rng.choice(OPEN_CODES)
            flag(self.add_claim(stranger, code, self.random_date(*recent), self.clean_units(code)),
                 "unknown_member", "eligibility_on_dos", "fail")

        # one digit of the Medicaid ID was keyed wrong; name and birth date are right
        for person in rng.sample(enrolled[10:], 8):
            code = rng.choice(OPEN_CODES)
            row = self.add_claim(person, code, self.free_dos(person, code, *recent), self.clean_units(code))
            while True:
                position = rng.randrange(10)
                digits = list(person.medicaid_id)
                digits[position] = str((int(digits[position]) + rng.randint(1, 9)) % 10)
                typo = "".join(digits)
                if typo not in self.ids_in_use:
                    break
            row.medicaid_id = typo
            flag(row, "member_id_typo", "eligibility_on_dos", "warn")

    # ---------------------------------------------------------------- messing

    def messy_date(self, d: date | None) -> str:
        if d is None:
            return ""
        style = self.rng.choices(["iso", "us", "us_short", "mon", "compact"], [45, 30, 10, 10, 5])[0]
        return {
            "iso": d.isoformat(),
            "us": d.strftime("%m/%d/%Y"),
            "us_short": d.strftime("%m/%d/%y"),
            "mon": f"{d.day:02d}-{calendar.month_abbr[d.month]}-{d.year}",
            "compact": d.strftime("%Y%m%d"),
        }[style]

    def messy_id_text(self, medicaid_id: str) -> str:
        style = self.rng.choices(["plain", "hyphen", "stripped", "padded"], [70, 15, 10, 5])[0]
        if style == "hyphen":
            return f"{medicaid_id[:4]}-{medicaid_id[4:7]}-{medicaid_id[7:]}"
        if style == "stripped":
            return medicaid_id.lstrip("0")
        if style == "padded":
            return f" {medicaid_id} "
        return medicaid_id

    def messy_first(self, first: str) -> str:
        rng = self.rng
        style = rng.choices(["plain", "upper", "nick", "typo", "initial"], [68, 10, 8, 7, 7])[0]
        if style == "upper":
            return first.upper()
        if style == "nick" and first in NICKNAMES:
            return NICKNAMES[first]
        if style == "typo" and len(first) >= 6:
            i = rng.randrange(2, len(first) - 1)
            return first[:i] + first[i + 1] + first[i] + first[i + 2:]
        if style == "initial":
            return f"{first} {rng.choice('ABCDEJLMRS')}."
        return first

    def messy_last(self, last: str) -> str:
        rng = self.rng
        style = rng.choices(["plain", "upper", "short", "space"], [75, 12, 8, 5])[0]
        if style == "upper":
            return last.upper()
        if style == "short" and "-" in last:
            return last.split("-")[0]
        if style == "space":
            return last + "  "
        return last

    def messy_patient_name(self, first: str, last: str) -> str:
        rng = self.rng
        if rng.random() < 0.06 and first in NICKNAMES:
            first = NICKNAMES[first]
        style = rng.choices(["last_first_upper", "first_last", "last_first_initial"], [50, 35, 15])[0]
        if style == "last_first_upper":
            return f"{last.upper()}, {first.upper()}"
        if style == "last_first_initial":
            return f"{last}, {first} {rng.choice('ABCDEJLMRS')}."
        return f"{first} {last}"

    def messy_money(self, amount: float) -> str:
        text = f"{amount:,.2f}" if self.rng.random() < 0.5 else f"{amount:.2f}"
        return f"${text}" if self.rng.random() < 0.3 else text

    def messy_provider(self, npi: str) -> str:
        name = dict(PROVIDERS)[npi]
        return self.rng.choices([name, name.upper(), f"{name} "], [80, 12, 8])[0]

    # ----------------------------------------------------------------- writers

    def write_claims(self, path: Path) -> int:
        rng = self.rng
        rows = []
        for c in self.claims:
            auth = c.auth_number
            if auth and rng.random() < 0.12:
                auth = rng.choice([auth.lower(), f"{auth[:2]} {auth[2:]}", f"{auth[:2]}-{auth[2:]}"])
            rows.append({
                "Claim #": c.number,
                "Patient Name": self.messy_patient_name(c.first, c.last),
                "Member ID": self.messy_id_text(c.medicaid_id),
                "DOB": self.messy_date(c.dob),
                "Rendering NPI": c.npi,
                "Rendering Provider": self.messy_provider(c.npi),
                "Proc Code": rng.choices([c.code, c.code.lower(), f"{c.code} "], [85, 8, 7])[0],
                "DOS": self.messy_date(c.dos),
                "Units": rng.choices([str(c.units), f"{c.units}.0", f" {c.units} "], [80, 12, 8])[0],
                "Charge": self.messy_money(c.charge),
                "Auth #": auth,
                "Created": self.messy_date(c.created),
            })
        rows.extend(dict(r) for r in rng.sample(rows, 12))  # export glitch: rows repeated verbatim
        rng.shuffle(rows)
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return len(rows)

    def write_roster(self, path: Path, truth_path: Path) -> int:
        rng = self.rng
        workbook = Workbook()
        workbook.remove(workbook.active)
        truth: list[tuple[str, int, int]] = []
        for month_index, (year, month) in enumerate(ROSTER_MONTHS):
            sheet_name = f"{year}-{month:02d}"
            sheet = workbook.create_sheet(sheet_name)
            sheet.append(["Monthly Eligibility Roster"])
            sheet.append([f"Report month: {sheet_name}"])
            sheet.append([])
            sheet.append(["Medicaid ID", "Last Name", "First Name", "DOB", "Elig Start", "Elig End", "Plan"])
            first_day = date(year, month, 1)
            last_day = date(year, month, calendar.monthrange(year, month)[1])
            entries = [p for p in self.people if month_index in p.months]
            entries += rng.sample(entries, max(1, len(entries) // 25))  # same person keyed twice
            rng.shuffle(entries)
            for person in entries:
                medicaid_id = person.id_in_month(month_index)
                id_style = rng.choices(["text", "number", "hyphen", "blank"], [62, 20, 12, 6])[0]
                id_cell: object = medicaid_id
                if id_style == "number":
                    id_cell = int(medicaid_id)  # the spreadsheet drops leading zeros
                elif id_style == "hyphen":
                    id_cell = f"{medicaid_id[:4]}-{medicaid_id[4:7]}-{medicaid_id[7:]}"
                elif id_style == "blank":
                    id_cell = None
                dob_cell: object = person.dob if rng.random() < 0.5 else self.messy_date(person.dob)
                end = last_day
                if person.term_date and person.term_date.month == month:
                    end = person.term_date
                end_cell: object = end if rng.random() < 0.9 or end != last_day else None
                start_cell: object = first_day if rng.random() < 0.7 else self.messy_date(first_day)
                sheet.append([id_cell, self.messy_last(person.last), self.messy_first(person.first),
                              dob_cell, start_cell, end_cell, PLANS[person.pid % 2]])
                truth.append((sheet_name, sheet.max_row, person.pid))
        workbook.save(path)
        with truth_path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["sheet_name", "row_number", "person_id"])
            writer.writerows(truth)
        return len(truth)

    def write_authorizations(self, path: Path) -> int:
        rng = self.rng
        records = []
        for auth in self.auths:
            person = self.people[auth.pid]
            medicaid_id = person.new_medicaid_id if person.new_medicaid_id and rng.random() < 0.5 else person.medicaid_id
            updated = date(2025, 3, 1) + timedelta(days=rng.randrange(60))
            record = {
                "authNumber": auth.number,
                "status": rng.choice([auth.status.upper(), auth.status.capitalize(), auth.status]),
                "member": {
                    "medicaidId": self.messy_id_text(medicaid_id),
                    "lastName": person.last,
                    "firstName": person.first,
                    "dob": self.messy_date(person.dob),
                },
                "service": {"code": auth.code, "description": SERVICES[auth.code][0]},
                "provider": {"npi": auth.npi, "name": dict(PROVIDERS)[auth.npi]},
                "effective": {"start": self.messy_date(auth.start), "end": self.messy_date(auth.end) or None},
                "unitsApproved": auth.units if rng.random() < 0.7 else str(auth.units),
                "updatedAt": f"{updated.isoformat()}T{rng.randrange(8, 18):02d}:{rng.randrange(60):02d}:00Z",
            }
            if rng.random() < 0.1:  # an earlier revision of the same auth is still in the feed
                earlier = json.loads(json.dumps(record))
                earlier["status"] = "PENDING"
                earlier["unitsApproved"] = max(1, auth.units // 2)
                earlier["updatedAt"] = f"{(updated - timedelta(days=9)).isoformat()}T09:00:00Z"
                records.append(earlier)
            records.append(record)
        rng.shuffle(records)
        feed = {"feed": "prior-authorizations", "generatedAt": f"{AS_OF.isoformat()}T06:00:00Z",
                "authorizations": records}
        path.write_text(json.dumps(feed, indent=2))
        return len(records)

    def write_claims_truth(self, path: Path) -> None:
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["claim_id", "defect", "expected_rule", "expected_status"])
            for c in self.claims:
                writer.writerow([c.number, c.defect, c.expected_rule, c.expected_status])

    def run(self, out_dir: Path) -> dict:
        raw_dir, truth_dir = out_dir / "raw", out_dir / "truth"
        raw_dir.mkdir(parents=True, exist_ok=True)
        truth_dir.mkdir(parents=True, exist_ok=True)
        self.build_people()
        self.build_standard_auths()
        self.build_clean_claims()
        self.build_defect_claims()
        manifest = {
            "seed": self.seed,
            "as_of": AS_OF.isoformat(),
            "people": len(self.people),
            "claims": len(self.claims),
            "claim_rows": self.write_claims(raw_dir / "claims_export.csv"),
            "roster_rows": self.write_roster(raw_dir / "member_roster.xlsx", truth_dir / "roster_truth.csv"),
            "authorization_records": self.write_authorizations(raw_dir / "authorizations.json"),
        }
        self.write_claims_truth(truth_dir / "claims_truth.csv")
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        return manifest


def generate(out_dir: Path, seed: int = 42) -> dict:
    return Generator(seed=seed).run(Path(out_dir))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic, deliberately messy source data.")
    parser.add_argument("--out", type=Path, default=Path("data"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    print(json.dumps(generate(args.out, args.seed), indent=2))


if __name__ == "__main__":
    main()

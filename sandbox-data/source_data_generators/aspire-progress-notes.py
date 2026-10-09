"""Clinical progress notes for the last 10 days, and the watch words in each.

Run: python manage.py progress_notes --regenerate
Written once by a seed or the first update; each later update moves every
note's date forward to end on the latest day (see DailyProgressNotes).

Every resident in a bed gets notes as care teams write them: on a given day a
nursing note about one time in three, therapy one in ten, and physician,
dietary, social service and activities notes now and then -- about 0.55 notes
a resident a day. Only the 10 days to the latest simulated day are kept: Flagged
Progress Notes reviews no further back.

A note is an opening, a middle sentence and a closing from its type's own
sentences. In about 12% the middle is a finding -- a fall, coughing, a pressure
ulcer, a resident wanting to leave AMA -- and in a quarter of those a second
finding follows. FLAG_TERMS are then found in the finished text as whole
words, case-insensitive, as a reviewer's search would: flagging reads the text,
not how it was written. The routine sentences are checked at import to contain
none of them.

Notes are signed by a small roster per facility and note type: "RN K. Patel".
Every draw comes from stay ids, the day and the note type, so a rebuild gives
the same notes.
"""
import re

from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from base import BaseGenerator, DailyGenerator, GenerationResult
from source_data_generators.draws import draw

THROUGH = "SELECT max(simulation_date) AS day FROM sandbox_daily_runs WHERE generator = 'adt'"
NOTE_DAYS = 10
FLAG_CHANCE, SECOND_FLAG_CHANCE = 0.12, 0.25

FLAG_TERMS = (
    'aggressive', 'ama', 'cough', 'coughing', 'decline', 'emesis', 'fall', 'fluids', 'fracture', 'hospital',
    'hydration', 'infection', 'injury', 'isolation', 'lethargic', 'nectar', 'normal saline', 'nutritional shakes',
    'open area', 'pna', 'pneumonia', 'pressure', 'red', 'reddened', 'redness', 'sepsis', 'septic', 'septicemia',
    'shortness of breath', 'sob', 'thick', 'ulcer', 'wandering', 'wheezing', 'wound',
)

LAST_NAMES = ('Patel', 'Hart', 'Wallace', 'Alvarez', 'Kim', 'Brooks', 'Nguyen', 'Okafor', 'Reyes', 'Murphy',
    'Chen', 'Foster', 'Hughes', 'Bennett', 'Diaz', 'Coleman', 'Price', 'Sanders', 'Ward', 'Ramirez',
    'Jenkins', 'Perry', 'Long', 'Ross', 'Morales', 'Powell', 'Sullivan', 'Russell', 'Ortiz', 'Fisher')
INITIALS = 'ABCDEGHJKLMNPRSTW'

# Per note type: the chance a resident gets one on a day, how many clinicians
# write them per facility, their credentials, and the sentences.
NOTE_TYPES = {
    'Nursing': dict(chance=0.30, writers=6, credentials=('RN', 'LPN', 'RN', 'LPN', 'CNA', 'RN'),
        openings=(
            'Resident alert and oriented x3, pleasant and cooperative with care this shift.',
            'Resident resting in bed with call light within reach; no acute distress noted.',
            'Vital signs within normal limits; resident denies pain at this time.',
            'Resident ate most of breakfast and took medications whole without difficulty.',
            'Resident up in wheelchair for meals and participated in morning care.',
            'Resident slept through the night with no complaints voiced.',
        ),
        middles=(
            'Skin warm and dry, intact to visible areas.',
            'Continent of bowel and bladder; incontinence care provided as needed.',
            'Medications administered as ordered; resident tolerated well.',
            'Transferred with assist of one using gait belt without issue.',
            'Lung sounds clear bilaterally; respirations even and unlabored.',
            'Family visited this afternoon and resident appeared in good spirits.',
        ),
        closings=(
            'Will continue to monitor per plan of care.',
            'Call light within reach, bed in lowest position.',
            'Care plan reviewed; no changes at this time.',
            'Will update the oncoming nurse at shift report.',
        ),
        findings=(
            'Resident found on floor beside bed at 0300; unwitnessed fall, no apparent injury, neuro checks initiated.',
            'Resident noted coughing and wheezing this shift; temp 100.8, provider notified of possible pneumonia.',
            'Resident lethargic and difficult to arouse; provider notified, sent to hospital for evaluation of possible sepsis.',
            'Stage 2 pressure ulcer to coccyx measured 1.5 x 1.0 cm; wound bed pink with surrounding redness.',
            'Reddened area noted to left heel; heels offloaded and open area dressed per wound care orders.',
            'Shortness of breath on exertion, SOB noted with transfers; oxygen applied at 2 L.',
            'Resident had two episodes of emesis after lunch; encouraged fluids and monitoring hydration.',
            'Resident wandering in hallways and exit seeking; became aggressive when redirected by staff.',
            'Resident placed on contact isolation pending culture results for suspected infection.',
            'Resident refusing care and stated intent to leave AMA; provider and family notified.',
            'Provider ordered normal saline IV for dehydration; resident remains lethargic.',
            'Skin tear to right forearm after a fall against wheelchair; injury cleansed and dressed.',
            'X-ray ordered for left hip pain after fall to rule out fracture.',
            'Urine cloudy with strong odor; provider notified of possible infection and culture obtained.',
            'Resident with productive cough; PNA suspected, chest x-ray ordered.',
            'Resident returned from hospital with diagnosis of septicemia; IV antibiotics continue.',
            'Sacral area red and non-blanching; repositioned every two hours to relieve pressure.',
        )),
    'Therapy': dict(chance=0.10, writers=3, credentials=('PT', 'OT', 'ST'),
        openings=(
            'Patient seen for skilled therapy session addressing functional mobility and strength.',
            'Patient participated in 45-minute session focused on ADL retraining.',
            'Speech therapy session completed targeting swallow function and safe meal strategies.',
        ),
        middles=(
            'Patient ambulated 150 feet with rolling walker and contact guard assist.',
            'Patient completed upper body dressing with set-up assist and verbal cues.',
            'Therapeutic exercise performed for lower extremity strengthening, 3 sets of 10.',
            'Patient tolerated regular diet trials without signs of aspiration.',
        ),
        closings=(
            'Continue skilled therapy per plan of care.',
            'Progressing toward short-term goals; will reassess next week.',
            'Patient educated on home exercise program and verbalized understanding.',
        ),
        findings=(
            'Patient with functional decline since last week; endurance reduced and requires increased assist.',
            'Patient coughing with thin liquids; recommend nectar thick liquids and SLP follow-up.',
            'Session limited by shortness of breath and wheezing with exertion; nursing notified.',
            'Patient reports a fall over the weekend; balance and gait reassessed, fall risk high.',
            'Patient lethargic and unable to participate; session deferred and nursing notified.',
            'Right shoulder pain following injury; range of motion limited, fracture ruled out per x-ray.',
            'Pressure relief and positioning program started for a reddened area on the sacrum.',
        )),
    'Physician': dict(chance=0.04, writers=2, credentials=('MD', 'NP'),
        openings=(
            'Seen and examined for routine follow-up of chronic conditions.',
            'Monthly visit; chart, medications and labs reviewed.',
        ),
        middles=(
            'Heart regular rate and rhythm, lungs clear, abdomen soft and non-tender.',
            'Blood sugars reviewed and remain at goal on current regimen.',
            'Labs reviewed and stable; no medication changes.',
        ),
        closings=(
            'Continue current plan; follow up in 30 days or sooner as needed.',
            'Discussed plan with nursing staff.',
        ),
        findings=(
            'Assessment: community-acquired pneumonia; start oral antibiotics and repeat chest x-ray in two weeks.',
            'Suspect early sepsis with fever and hypotension; transfer to hospital for evaluation.',
            'Stage 3 pressure ulcer to sacrum, wound care to follow; add nutritional shakes twice daily.',
            'Urinary tract infection confirmed on culture; start antibiotics and push fluids.',
            'Weight and cognitive decline over past month; goals of care discussion with family scheduled.',
            'Redness and warmth to left lower leg concerning for cellulitis infection; start antibiotics.',
            'Dehydration noted on labs; start normal saline and encourage hydration.',
            'Hip pain after fall; x-ray shows no fracture, continue pain management.',
            'Recent septic presentation; septicemia treated at hospital, continue to monitor.',
        )),
    'Dietary': dict(chance=0.03, writers=1, credentials=('RD',),
        openings=(
            'Nutrition review completed; current diet regular texture with thin liquids.',
            'Quarterly nutrition assessment completed.',
        ),
        middles=(
            'Meal intake averaging 75 to 100 percent per records.',
            'Resident reports food preferences honored and is satisfied with meals.',
            'Labs within normal limits; no nutrition concerns identified.',
        ),
        closings=(
            'Continue current diet order.',
            'Will follow up at next quarterly review or as needed.',
        ),
        findings=(
            'Weight decline of 6 lbs in 30 days; recommend nutritional shakes twice daily with meals.',
            'Poor fluid intake noted; encourage fluids between meals to support hydration.',
            'Diet changed to nectar thick liquids per SLP recommendation.',
            'Increased protein needs for healing of sacral pressure ulcer; supplement added.',
            'Emesis after meals reported this week; diet advanced as tolerated, monitor intake.',
        )),
    'Social Service': dict(chance=0.03, writers=1, credentials=('SW',),
        openings=(
            'Social services visit completed; resident pleasant and engaged in conversation.',
            'Met with resident and family for care plan meeting.',
        ),
        middles=(
            'Resident reports adjusting well to the facility and denies concerns.',
            'Discharge planning reviewed; resident plans long-term placement.',
            'Mood stable; resident enjoys visits from family.',
        ),
        closings=(
            'Social services will continue to follow.',
            'Family contact information updated in the record.',
        ),
        findings=(
            'Resident expressed wish to leave AMA; risks reviewed and family contacted.',
            'Staff report increased wandering and aggressive behavior; behavior monitoring initiated.',
            'Resident tearful and withdrawn since isolation precautions began; supportive visits increased.',
            'Family concerned about recent decline in mood and appetite; psych referral offered.',
            'Resident returned from hospital; readjustment and safety plan reviewed with family.',
        )),
    'Activities': dict(chance=0.04, writers=1, credentials=('AD',),
        openings=(
            'Resident attended morning exercise group and participated actively.',
            "One-to-one visit completed in resident's room.",
            'Resident attended music program in the activity room.',
        ),
        middles=(
            'Resident enjoyed conversation about past hobbies and family.',
            'Resident completed puzzle activity with minimal cues.',
            'Resident sang along and appeared to enjoy the program.',
        ),
        closings=(
            'Will continue to invite to preferred activities.',
            'Activity preferences reviewed and calendar provided.',
        ),
        findings=(
            'Resident unable to attend group due to isolation precautions; in-room visit provided.',
            'Resident left group early, wandering toward exit; staff redirected.',
            'Resident became aggressive with peer during bingo; separated and nursing informed.',
            'Resident noted coughing throughout program; nursing informed.',
            'Participation decline noted over past two weeks; will encourage in-room visits.',
        )),
}
assert tuple(NOTE_TYPES) == schema.NOTE_TYPES


def _terms_in(text):
    return [term for term in FLAG_TERMS if re.search(rf'\b{re.escape(term)}\b', text, re.IGNORECASE)]


# The routine sentences must not flag a note by themselves, and every finding
# must: otherwise the 12% would not be the share flagged.
for _kind, _rules in NOTE_TYPES.items():
    for _sentence in _rules['openings'] + _rules['middles'] + _rules['closings']:
        assert not _terms_in(_sentence), (_kind, _sentence, _terms_in(_sentence))
    for _sentence in _rules['findings']:
        assert _terms_in(_sentence), (_kind, _sentence)
    assert '%' not in ''.join(_rules['openings'] + _rules['middles'] + _rules['closings'] + _rules['findings'])


def _literal(text):
    return "'" + text.replace("'", "''") + "'"


def _array(values):
    return 'ARRAY[' + ', '.join(_literal(value) for value in values) + ']::text[]'


def _pick(array, seed):
    return f'({array})[1 + floor({draw(seed)} * cardinality({array}))::int]'


def notes_sql(table):
    types = ' UNION ALL '.join(
        f"SELECT {_literal(kind)} AS note_type, {rules['chance']} AS chance, {rules['writers']} AS writers, "
        f"{_array(rules['credentials'])} AS credentials, {_array(rules['openings'])} AS openings, "
        f"{_array(rules['middles'])} AS middles, {_array(rules['closings'])} AS closings, "
        f"{_array(rules['findings'])} AS findings"
        for kind, rules in NOTE_TYPES.items())
    seed = "n.stay_id::text || ':' || n.note_date || ':' || n.note_type"
    writer = "n.facility_id::text || ':' || n.note_type || ':' || n.writer"
    # Whole words, case-insensitive, as a reviewer's search would find them.
    terms = _array(FLAG_TERMS)
    return f"""
WITH through AS ({THROUGH}), days AS (
    SELECT d::date AS note_date
    FROM generate_series((SELECT day FROM through) - {NOTE_DAYS - 1}, (SELECT day FROM through), interval '1 day') d
), types AS ({types}), in_bed AS (
    -- Everyone in a bed each day, with that day's payer.
    SELECT l.stay_id, l.resident_id, l.facility_id, l.payer_id, d.note_date
    FROM days d JOIN census_logs l ON l.in_bed @> d.note_date
), notes AS (
    SELECT b.*, t.*,
           floor({draw("b.stay_id::text || ':' || b.note_date || ':' || t.note_type || ':writer'")} * t.writers)::int
             AS writer
    FROM in_bed b CROSS JOIN types t
    WHERE {draw("b.stay_id::text || ':' || b.note_date || ':' || t.note_type")} < t.chance
), written AS (
    SELECT md5('note:' || {seed})::uuid AS note_id, n.stay_id, n.resident_id, n.facility_id, n.note_date,
           n.note_type, n.payer_id,
           n.credentials[1 + n.writer] || ' ' || substr({_literal(INITIALS)},
               1 + floor({draw(writer + " || ':initial'")} * {len(INITIALS)})::int, 1) || '. '
             || ({_array(LAST_NAMES)})[1 + floor({draw(writer + " || ':name'")} * {len(LAST_NAMES)})::int]
             AS clinician,
           {_pick('n.openings', seed + " || ':opening'")}
             || ' ' || CASE WHEN {draw(seed + " || ':finding'")} < {FLAG_CHANCE}
                  THEN {_pick('n.findings', seed + " || ':first'")}
                    || CASE WHEN {draw(seed + " || ':second'")} < {SECOND_FLAG_CHANCE}
                         THEN ' ' || {_pick('n.findings', seed + " || ':second finding'")} ELSE '' END
                  ELSE {_pick('n.middles', seed + " || ':middle'")} END
             || ' ' || {_pick('n.closings', seed + " || ':closing'")} AS note_text
    FROM notes n
)
INSERT INTO {table} (note_id, stay_id, resident_id, facility_id, note_date, note_type, clinician, payer_id,
    note_text, flag_terms)
SELECT w.note_id, w.stay_id, w.resident_id, w.facility_id, w.note_date, w.note_type, w.clinician, w.payer_id,
       w.note_text,
       ARRAY(SELECT term FROM unnest({terms}) AS term
             WHERE w.note_text ~* ('\\m' || term || '\\M') ORDER BY term)
FROM written w
ORDER BY w.note_date, w.facility_id
"""


class ProgressNotesGenerator(BaseGenerator):
    name = 'progress_notes'
    table = schema.progress_notes
    depends_on = ('census_logs',)
    transaction_isolation = 'REPEATABLE READ'

    def expected_rows(self):
        return None

    def generate(self):
        raise ValueError('Progress notes are built directly with INSERT ... SELECT.')

    def write_generated(self, connection):
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        table = self._table_identifier(self.table)
        if self.progress:
            self.progress.set_phase('Remove previous notes')
        connection.exec_driver_sql(sql.SQL('TRUNCATE {}').format(table).as_string(driver))
        suspended = self.suspend_indexes(connection, self.table)
        if self.progress:
            self.progress.set_phase(f'Write the last {NOTE_DAYS} days of notes')
        generated = connection.exec_driver_sql(notes_sql(table.as_string(driver))).rowcount
        if self.progress:
            self.progress.set_phase('Rebuild keys', details=f'{generated:,} notes')
        self.restore_indexes(connection, self.table, suspended)
        return GenerationResult(generated=generated, changed=generated)


GENERATORS = (ProgressNotesGenerator,)


class DailyProgressNotes(DailyGenerator):
    """Written once, then moved: when days are added, every note's date shifts
    forward by as many days, so the 10 days always end on the latest one. A
    whole build -- minutes -- happens only for the first build, a reset, a rule
    change, or a gap of more than 10 days, when nearly every day is asked for.
    A moved note keeps its resident and text, so in time some belong to
    residents since discharged; --regenerate draws them afresh.

    A checkpoint's count is that day's notes, zero for days before the window,
    whose notes are not kept."""
    name = 'progress_notes'
    table = schema.progress_notes
    owned_tables = (table,)
    depends_on = ('census_logs',)
    bulk_dates = True

    def run_dates(self, connection, days):
        latest = connection.scalar(select(func.max(schema.daily_runs.c.simulation_date))
            .where(schema.daily_runs.c.generator == 'adt'))
        newest = connection.scalar(select(func.max(self.table.c.note_date)))
        if newest is None or len(days) > NOTE_DAYS:
            builder = ProgressNotesGenerator(self.database_url)
            builder.progress = self.progress
            builder.write_generated(connection)
        elif latest > newest:
            if self.progress:
                self.progress.set_phase(f'Move notes forward {(latest - newest).days} days')
            connection.execute(self.table.update().values(note_date=self.table.c.note_date + (latest - newest)))
        counts = dict(connection.execute(select(self.table.c.note_date, func.count())
            .where(self.table.c.note_date.in_(days))
            .group_by(self.table.c.note_date)).all())
        return {day: {self.table.name: counts.get(day, 0)} for day in days}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyProgressNotes,)

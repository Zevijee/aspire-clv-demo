"""Compatibility adapter. Referral aggregation is owned entirely by reporting."""
from seeding.base import BaseSeeder, SeedResult
from data.models.hospital_reporting import metadata, hospitals, monthly, publication

class ReferringHospitalsSeeder(BaseSeeder):
    name = 'referring_hospitals'
    dependencies = ()
    def seed(self,context):
        from reporting.runner import refresh_one
        count = refresh_one(context.connection,self.name,context.window.start_date,context.window.end_date,
            facility_codes=context.facility_codes)
        return SeedResult(self.name,count,count)
    def validate(self,context,result):
        return None

if __name__ == '__main__':
    from seeding.cli import main
    raise SystemExit(main(targets=('referring_hospitals',)))

from data.models.bed_holds import metadata


def upgrade(connection):
    metadata.create_all(connection)

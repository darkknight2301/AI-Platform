class ReminderError(Exception):
    """Base class for reminder-engine errors."""


class InvalidReminderError(ReminderError):
    pass


class DuplicateReminderError(ReminderError):
    pass


class ReminderNotFoundError(ReminderError):
    pass

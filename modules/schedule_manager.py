import sched
import time
from modules.log_manager import LogManager

class ScheduleManager:
    """
    ScheduleManager handles the scheduling of updates at specified intervals.

    Attributes:
        timezone (int): The timezone offset in hours. Used to display the next update time.
        delay (int): The delay between updates in minutes.
        scheduler (sched.scheduler): The scheduler object.
        logger (Logger): The logger

    Methods:
        get_next_update_time(): Returns the next update time based on the current time, timezone, and delay.
        schedule_update(callback): Schedules the next update.
        run(): Runs the scheduler indefinitely.
    """
    def __init__(self, timezone, delay):
        """
        Initializes the ScheduleManager object.

        Args:
            timezone (int): The timezone offset in hours. Used to display the next update time.
            delay (int): The delay between updates in minutes.
        """
        self.logger = LogManager.setup_logger('SCH')
        self.timezone = timezone
        self.delay = delay
        self.scheduler = sched.scheduler(time.time, time.sleep)
        self.logger.debug('Scheduler Module initialized.')

    def get_next_update_time(self):
        """
        Returns the next update time based on the current time, timezone, and delay.

        Returns:
            float: The next update time
        """
        current_time = (time.time() + ((60 * 60) * self.timezone))
        return (current_time - (current_time % (self.delay * 60))) + (self.delay * 60)

    def schedule_update(self, callback):
        """
        Schedules the next update.

        Args:
            callback (function): The function to call when the update is scheduled
        """
        next_time = self.get_next_update_time() - (3600 * self.timezone)
        self.logger.info(f"Next update scheduled for {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(next_time))}.")
        self.scheduler.enterabs(next_time, 1, callback, ())

    def run(self):
        """
        Runs the scheduler indefinitely.
        """
        while True:
            try:
                self.scheduler.run(blocking=False)
                time.sleep(5)
            except KeyboardInterrupt:
                self.logger.info("Exiting...")
                break
import sched
import time
from modules.log_manager import LogManager

class ScheduleManager:
    """
    Manages scheduled updates for the bot at specified intervals.

    This class provides a scheduling system that allows the bot to perform
    updates at regular intervals. It uses Python's built-in sched module
    for scheduling and includes timezone support for accurate scheduling.

    Attributes:
        timezone (int): The timezone offset in hours from UTC.
        delay (int): The delay between updates in minutes.
        scheduler (sched.scheduler): The scheduler instance.
        logger (Logger): The logger instance for this class.

    Example:
        >>> scheduler = ScheduleManager(timezone=0, delay=60)
        >>> scheduler.schedule_update(callback_function)
        >>> scheduler.run()
    """

    def __init__(self, timezone: int, delay: int):
        """
        Initializes the ScheduleManager with timezone and delay settings.

        Args:
            timezone (int): The timezone offset in hours from UTC.
                           Used to display the next update time in the correct timezone.
            delay (int): The delay between updates in minutes.
                        This determines how often the scheduled callback will run.

        Note:
            The scheduler uses the system's time.time() function for timing
            and time.sleep() for waiting between checks.
        """
        self.logger = LogManager.setup_logger('SCH')
        self.timezone = timezone
        self.delay = delay
        self.scheduler = sched.scheduler(time.time, time.sleep)
        self.logger.debug('Scheduler Module initialized.')

    def get_next_update_time(self) -> float:
        """
        Calculates the next scheduled update time.

        This method calculates the next update time based on the current time,
        timezone offset, and delay. It ensures updates occur at regular intervals
        aligned with the specified timezone.

        Returns:
            float: The Unix timestamp for the next scheduled update.

        Example:
            >>> scheduler = ScheduleManager(timezone=0, delay=60)
            >>> next_time = scheduler.get_next_update_time()
            >>> print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(next_time)))
        """
        current_time = (time.time() + ((60 * 60) * self.timezone))
        return (current_time - (current_time % (self.delay * 60))) + (self.delay * 60)

    def schedule_update(self, callback: callable):
        """
        Schedules the next update using the provided callback function.

        This method calculates the next update time and schedules the callback
        function to run at that time. It logs the scheduled time for reference.

        Args:
            callback (callable): The function to call when the update is scheduled.
                               This function should not take any arguments.

        Note:
            The callback function will be called with no arguments when the
            scheduled time is reached.
        """
        next_time = self.get_next_update_time() - (3600 * self.timezone)
        self.logger.info(f"Next update scheduled for {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(next_time))}.")
        self.scheduler.enterabs(next_time, 1, callback, ())

    def run(self):
        """
        Runs the scheduler indefinitely until interrupted.

        This method enters an infinite loop that:
        1. Runs any pending scheduled events
        2. Sleeps for 5 seconds
        3. Repeats until interrupted

        The scheduler can be interrupted by a KeyboardInterrupt (Ctrl+C),
        at which point it will log the exit and break the loop.

        Note:
            This method blocks the current thread until interrupted.
            It should typically be run in the main thread of the application.
        """
        while True:
            try:
                self.scheduler.run(blocking=False)
                time.sleep(5)
            except KeyboardInterrupt:
                self.logger.info("Exiting...")
                break
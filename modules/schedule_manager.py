import sched
import time
from modules.log_manager import LogManager

class ScheduleManager:
    def __init__(self, timezone, delay):
        self.logger = LogManager.setup_logger('SCH')
        self.timezone = timezone
        self.delay = delay
        self.scheduler = sched.scheduler(time.time, time.sleep)
        self.logger.debug('Scheduler Module initialized.')

    def get_next_update_time(self):
        # Calculate the next update time.
        current_time = (time.time() + ((60 * 60) * self.timezone))
        return (current_time - (current_time % (self.delay * 60))) + (self.delay * 60)
    
    def schedule_update(self, callback):
        # Schedules an event for the next update time.
        next_time = self.get_next_update_time() - (3600 * self.timezone)
        self.logger.info(f"Next update scheduled for {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(next_time))}.")
        self.scheduler.enterabs(next_time, 1, callback, ())

    def run(self):
        # Run the scheduler.
        while True:
            try:
                self.scheduler.run(blocking=False)
                time.sleep(5)
            except KeyboardInterrupt:
                self.logger.info("Exiting...")
                break
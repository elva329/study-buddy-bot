import logging
import os

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '../..'))
LOG_PATH = os.path.join(PROJECT_ROOT, 'logs', 'bot.log')

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

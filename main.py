import asyncio
import logging
from dotenv import load_dotenv
from deputy.models.config import AppConfig
from deputy.bot import DeputyBot

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

async def main():
    try:
        config = AppConfig.from_env()
        
        if not config.mattermost.url or not config.mattermost.token:
            logger.error("Missing Mattermost configuration (URL and TOKEN required)")
            return
        
        logger.info("Starting Deputy Bot...")
        bot = DeputyBot(config)
        await bot.start()
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    except KeyboardInterrupt:
        logger.info("Bot shutdown requested")

if __name__ == "__main__":
    asyncio.run(main())

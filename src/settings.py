import os
import boto3
from botocore import UNSIGNED
from dotenv import load_dotenv
from botocore.config import Config
from pretty_loguru import create_logger

load_dotenv()

'''
    - for prod deployment sensitive 
    credentials should be set in .env file 
    for the purposes of this chal i will hardcode them here 
    but i'm not going to commit .env file with the credentials in it -- well same same but different.

'''


class Settings:
    AWS_REGION: str = os.getenv("AWS_REGION", "af-south-1")
    S3_BUCKET: str = os.getenv("S3_BUCKET", "cct-ds-code-challenge-input-data")

    HEX_RES8_KEY: str = os.getenv("HEX_RES8_KEY", "city-hex-polygons-8.geojson")
    HEX_RES8_10_KEY: str = os.getenv("HEX_RES8_10_KEY", "city-hex-polygons-8-10.geojson")
    SR_HEX_KEY: str = os.getenv("SR_HEX_KEY", "sr_hex.csv.gz")
    SR_KEY: str = os.getenv("SR_KEY", "sr.csv.gz")

    AWS_ACCESS_KEY_ID: str | None = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY: str | None = os.getenv("AWS_SECRET_ACCESS_KEY")

    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "outputs")
    LOG_DIR: str = os.getenv("LOG_DIR", "logs")

# i just love the color in prety_loguru - feel free to change the logger to your preferred logging library
logger = create_logger(
    name="cct_de_challenge",
    log_path=Settings.LOG_DIR,
    level=os.getenv("LOG_LEVEL", "INFO"),
)


def get_s3_client():
    '''
        returns an s3 client using the creds
        falls back to anonymous access if no creds not found
    '''
    if Settings.AWS_ACCESS_KEY_ID and Settings.AWS_SECRET_ACCESS_KEY:
        logger.info(f"accessing through AWS credentials ")
        return boto3.client(
            "s3",
            region_name=Settings.AWS_REGION,
            aws_access_key_id=Settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=Settings.AWS_SECRET_ACCESS_KEY,
        )

    logger.info("No credentials supplied — using anonymous S3 access.")
    return boto3.client(
        "s3",
        region_name=Settings.AWS_REGION,
        config=Config(signature_version=UNSIGNED),
    )

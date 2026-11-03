"""Demo app: screens CVs with an LLM. Deliberately leaky, used by the egress example."""

import os

import sentry_sdk
from openai import OpenAI

sentry_sdk.init(dsn=os.environ["SENTRY_DSN"], send_default_pii=True)
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def screen(candidate):
    prompt = f"Score this CV for {candidate['full_name']} ({candidate['email']}): {candidate['cv_text']}"
    return client.chat.completions.create(
        model="gpt-4.1", messages=[{"role": "user", "content": prompt}]
    )


def notify_recruiter(candidate):
    # see https://api.slack.com/messaging/webhooks
    import requests

    requests.post(os.environ["SLACK_WEBHOOK"], json={"text": candidate["email"]})

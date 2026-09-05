"""One-off check: confirm Razorpay and Gemini credentials actually authenticate."""
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def check_razorpay() -> None:
    import razorpay

    key_id = os.getenv("RAZORPAY_KEY_ID")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        print("RAZORPAY: FAIL - missing keys in .env")
        return
    client = razorpay.Client(auth=(key_id, key_secret))
    try:
        client.order.all({"count": 1})
        print("RAZORPAY: PASS - key_id/secret authenticated")
    except Exception as e:
        print(f"RAZORPAY: FAIL - {e}")


def check_gemini() -> None:
    from google import genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI: FAIL - missing key in .env")
        return
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Reply with exactly: OK",
        )
        print(f"GEMINI: PASS - model replied: {response.text.strip()}")
    except Exception as e:
        print(f"GEMINI: FAIL - {e}")


if __name__ == "__main__":
    check_razorpay()
    check_gemini()

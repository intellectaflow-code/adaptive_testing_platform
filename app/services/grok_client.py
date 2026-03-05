import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
)


async def generate_ai_quiz(topic: str, difficulty: str, num_questions: int):

    prompt = f"""
Generate {num_questions} multiple choice questions.

Topic: {topic}
Difficulty: {difficulty}

Requirements:
- Exactly 4 options per question
- Only ONE correct answer
- Do not include explanations
- Return ONLY valid JSON

Format:

[
  {{
    "question_text": "string",
    "options": ["A","B","C","D"],
    "correct_answer": "one of the options"
  }}
]
"""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": "You generate structured quiz questions."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.6,
    )

    content = response.choices[0].message.content

    try:
        return json.loads(content)
    except Exception:
        raise ValueError("AI returned invalid JSON")
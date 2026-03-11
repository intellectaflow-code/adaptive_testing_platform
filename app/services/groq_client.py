import os
import json
import re
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = AsyncOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
)


async def generate_ai_quiz(topic: str, difficulty: str, num_questions: int):

    prompt = f"""
Generate {num_questions} multiple choice questions.

Topic: {topic}
Difficulty: {difficulty}

Difficulty Rules:
- EASY → Foundational academic questions tailored for undergraduate Engineering/IT students. Focus on core university-level theoretical concepts, textbook definitions, standard algorithms, basic syntax, and fundamental architecture principles. Questions should test academic comprehension rather than general knowledge.
- MEDIUM → Scenario-based and practical application questions. Test the ability to apply theoretical concepts to real-world software development, system design, debugging, or IT operations. Focus on implementation details, best practices, engineering trade-offs, and project-based problem-solving.
- HARD → Advanced, complex questions requiring deep analytical thinking, troubleshooting, or research-level understanding. Focus on edge cases, algorithmic optimization at scale, complex distributed systems architecture, security vulnerabilities, or cutting-edge industry practices. The correct answer should require synthesizing multiple advanced concepts.

Requirements:
- Exactly 4 options per question
- Only ONE correct answer
- Options must be meaningful, plausible, and directly related to the topic to avoid obvious process-of-elimination guesses
- Do NOT include explanations
- Return ONLY valid JSON
- Do NOT include markdown blocks (like ```json) or any text outside the JSON array

Format:
[
  {{
    "question_text": "string",
    "options": ["A", "B", "C", "D"],
    "correct_answer": "exact string match of one of the options"
  }}
]
"""

    response = await client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": "You generate structured quiz questions."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.6,
    )

    content = response.choices[0].message.content.strip()

    # Extract JSON if model adds extra text
    try:
        json_match = re.search(r"\[.*\]", content, re.DOTALL)
        if json_match:
            content = json_match.group(0)

        data = json.loads(content)

    except Exception:
        raise ValueError("AI returned invalid JSON")

    # Validate response
    if not isinstance(data, list):
        raise ValueError("AI response format invalid")

    if len(data) != num_questions:
        raise ValueError("AI returned wrong number of questions")

    return data

# generate_ai_explanation

async def generate_ai_explanation(question_text: str, options: list[str], correct_answer: str) -> str:
    prompt = f"""
    Explain why the following answer is correct.

    Question:
    {question_text}

    Options:
    {options}

    Correct Answer:
    {correct_answer}

    Explain clearly in 2-3 sentences for a student.
    """

    response = await client.chat.completions.create(
        model="llama-3.1-8b-instant", # Using the same model as your quiz generator
        messages=[
            {"role": "system", "content": "You are a helpful and concise AI tutor."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3, # Lower temperature for more factual, less creative explanations
    )

    return response.choices[0].message.content.strip()
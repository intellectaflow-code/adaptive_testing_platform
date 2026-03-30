import os
import json
import re
import asyncio
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()




GROQ_API_KEY = os.getenv("GROQ_API_KEY")

print("GROQ_API_KEY VALUE:", os.getenv("GROQ_API_KEY"))


client = AsyncOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
)

BATCH_SIZE = 10  # Safe limit per single API call for this model


async def _generate_batch(topic: str, difficulty: str, num_questions: int) -> list:
    prompt = f"""
Generate exactly {num_questions} multiple choice questions.

Topic: {topic}
Difficulty: {difficulty}

Difficulty Rules:
- EASY → Foundational academic questions for undergraduate Engineering/IT students. Core theoretical concepts, textbook definitions, standard algorithms, basic syntax, fundamental architecture principles.
- MEDIUM → Scenario-based practical application questions. Apply concepts to real-world software development, system design, debugging, or IT operations.
- HARD → Advanced questions requiring deep analytical thinking. Edge cases, algorithmic optimization, complex distributed systems, security vulnerabilities, cutting-edge practices.

Requirements:
- Exactly 4 options per question
- Only ONE correct answer
- Options must be meaningful and plausible
- Do NOT include explanations
- Return ONLY a valid JSON array — no markdown, no extra text

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
        max_tokens=4096,  # ← key fix: explicitly raise the output limit
        messages=[
            {"role": "system", "content": "You generate structured quiz questions. Return ONLY a valid JSON array, no markdown, no extra text."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.6,
    )

    content = response.choices[0].message.content.strip()

    # Strip markdown fences if the model ignores instructions
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)

    # Fallback: extract JSON array if there's surrounding text
    json_match = re.search(r"\[.*\]", content, re.DOTALL)
    if json_match:
        content = json_match.group(0)

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"AI returned invalid JSON: {e}\nRaw: {content[:300]}")

    if not isinstance(data, list):
        raise ValueError("AI response is not a JSON array")

    return data


async def generate_ai_quiz(topic: str, difficulty: str, num_questions: int) -> list:
    """
    Splits large requests into concurrent batches of BATCH_SIZE to avoid
    token truncation, then merges and returns all questions.
    """
    if num_questions <= BATCH_SIZE:
        # Fast path — single call for small counts
        data = await _generate_batch(topic, difficulty, num_questions)
        if len(data) != num_questions:
            raise ValueError(f"Expected {num_questions} questions, got {len(data)}")
        return data

    # Build batch sizes: e.g. 25 → [10, 10, 5]
    batch_sizes = []
    remaining = num_questions
    while remaining > 0:
        batch_sizes.append(min(remaining, BATCH_SIZE))
        remaining -= batch_sizes[-1]

    # Run all batches concurrently
    results = await asyncio.gather(*[
        _generate_batch(topic, difficulty, size) for size in batch_sizes
    ])

    # Flatten batches into one list
    all_questions = [q for batch in results for q in batch]

    if len(all_questions) < num_questions:
        raise ValueError(
            f"Expected {num_questions} questions, got {len(all_questions)} "
            f"across {len(batch_sizes)} batches"
        )

    return all_questions[:num_questions]  # Trim any rare overflow


async def generate_ai_explanation(question_text: str, options: list[str], correct_answer: str) -> str:
    prompt = f"""
    Explain why the following answer is correct.

    Question: {question_text}
    Options: {options}
    Correct Answer: {correct_answer}

    Explain clearly in 2-3 sentences for a student.
    """

    response = await client.chat.completions.create(
        model="llama-3.1-8b-instant",
        max_tokens=300,
        messages=[
            {"role": "system", "content": "You are a helpful and concise AI tutor."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )

    return response.choices[0].message.content.strip()
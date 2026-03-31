# Quiz logic and helpers


import re


def parse_mcq_question(raw_text):
    """Parse a multiple choice question from LLM response"""
    lines = [l.strip() for l in raw_text.split('\n') if l.strip()]

    question_data = {
        'question': None,
        'options': [],
        'answer': None,
        'explanation': None
    }

    # Find the question line
    question_line = None
    for i, line in enumerate(lines):
        if line and not re.match(r'^[A-D]\)', line) and not line.startswith('Answer:') and not line.startswith('Explanation:'):
            question_line = line
            break

    if question_line:
        question_data['question'] = re.sub(
            r'^Q\d*:?\s*', '', question_line).strip()

    option_pattern = re.compile(r'^([A-D])[\.\):]\s*(.*)')
    for line in lines:
        match = option_pattern.match(line)
        if match:
            question_data['options'].append(match.group(2).strip())

    for line in lines:
        if line.startswith('Answer:'):
            answer_text = re.sub(r'^Answer:\s*', '', line).strip()
            letter_match = re.match(r'^([A-D])', answer_text, re.IGNORECASE)
            if letter_match:
                question_data['answer'] = letter_match.group(1).upper()
            else:
                question_data['answer'] = answer_text
            break

    for line in lines:
        if line.startswith('Explanation:'):
            question_data['explanation'] = re.sub(
                r'^Explanation:\s*', '', line).strip()
            break

    if (question_data['question'] and len(question_data['options']) == 4 and question_data['answer']):
        return question_data
    return None

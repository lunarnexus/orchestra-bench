def start_session(user_id, lesson_id, answers):
    return {'user_id': user_id, 'lesson_id': lesson_id, 'answers': list(answers), 'step': 0, 'score': 0, 'completed': False}

def submit_answer(session, answer):
    raise NotImplementedError('interactive progression not implemented')

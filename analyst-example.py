from analyst import summarize_keyword_conditions
from api.conversation import Conversation

c = summarize_keyword_conditions("notebook")

for (role, content) in c.transcript:
    print(f"{role}: {content}")
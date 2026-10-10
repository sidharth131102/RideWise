from openai import OpenAI
 
endpoint = "https://neo-hackathon.services.ai.azure.com/openai/v1/"
model_name = "gpt-oss-120b"
deployment_name = "Neo-Hackathon"
 
import os
api_key = os.getenv("LLM_API_KEY", "")  # set in .env; never hard-code the key
 
client = OpenAI(
    base_url=f"{endpoint}",
    api_key=api_key
)
 
completion = client.chat.completions.create(
    model=deployment_name,
    messages=[
        {
            "role": "user",
            "content": "What is the capital of France?",
        }
    ],
)
 
print(completion.choices[0].message)
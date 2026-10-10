from openai import OpenAI
 
endpoint = "https://neo-hackathon.services.ai.azure.com/openai/v1/"
model_name = "gpt-oss-120b"
deployment_name = "Neo-Hackathon"
 
api_key = "REDACTED-LLM-KEY"
 
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
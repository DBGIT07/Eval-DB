from app.sdk.tracer import track_llm

def fake_rag():
    prompt = "What is capital of Gujarat?"
    context = ["Capital of Gujarat is Ahmedabad."]
    response = "The capital of Gujarat is Ahmedabad."

    track_llm(
        prompt=prompt,
        response=response,
        model="gpt-4",
        context=context,
        latency_ms=120
    )

fake_rag()

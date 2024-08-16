from django.shortcuts import render
from django.views import View
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
import json, requests, time
from . import models

from environs import Env

# Initialize environs
env = Env()
env.read_env()

# RELEVANCE STATIC STUFF
RELEVANCE_REGION = env.str('RELEVANCE_REGION')
REGION_SPECIFIC_RELEVANCE_BASE_URL = env.str('RELEVANCE_API_BASE_URL').format(region=RELEVANCE_REGION)
RELEVANCE_PROJECT_ID = env.str('RELEVANCE_PROJECT_ID')
RELEVANCE_API_KEY = env.str('RELEVANCE_API_KEY')
RELEVANCE_AUTHORIZATION_TOKEN = env.str('RELEVANCE_AUTHORIZATION_TOKEN')
MAX_POLL_ATTEMPTS = 120
POLL_DELAY = 1

@csrf_exempt
def handleVAPIServerMessages(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)
    try:
        # Assuming the POST data is sent as JSON
        request_data = json.loads(request.body)

        type_status = request_data.get('message').get('type')
        if type_status == 'status-update':
            message_status = request_data.get('message').get('status')
            if message_status == 'in-progress':
                # do some work at the start of the call
                print(f"VAPI Server Message Status: {message_status}" )
            elif message_status == 'ended':
                # do some work at the end of the call
                # remove conversation object from db
                models.Conversation.remove_all()
                print(f"VAPI Server Message Status: {message_status}" )

        elif type_status == "end-of-call-report":
            # do some work with the end of call report
            print(f"VAPI Server Message Status: {type_status}" )
      
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    
    return JsonResponse(request_data, status=200, safe=False)

def trigger_agent(relevance_agent_id, user_content):   
    url = f"{REGION_SPECIFIC_RELEVANCE_BASE_URL}/agents/trigger"
    payload = {
        "message": {
            "role": "user",
            "content": user_content
        },
        "agent_id": relevance_agent_id
    }

    # query db for existence of conversation_id
    conversations = models.Conversation.objects.all()
    if conversations.exists():
        for conversation in conversations:
            if conversation.relevance_conversation_id != '1234':
                # this is NOT the first message in conversation
                conversation_id = conversation.relevance_conversation_id
                payload["conversation_id"] = conversation_id

    else:
        print('No conversations found')

    headers = {
        'Content-Type': 'application/json',
        'Authorization': RELEVANCE_AUTHORIZATION_TOKEN
       
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        json_response = response.json()

        print(f"API TRIGGER AGENT Response: {json_response}")
        return JsonResponse(json_response, status=200, safe=False)

    except requests.exceptions.RequestException as e:
            # Handle any errors in the request
            error_message = str(e)
            return JsonResponse({'error': f'API request failed: {error_message}'}, status=500)

def poll_for_updates(studio_id, job_id):
    """
    Poll the relevance.ai API for updates on a specific job.
    Args:
        studio_id (str): The ID of the studio.
        job_id (str): The ID of the job to poll for.
    Returns:
        dict: The output of the completed job, or None if polling fails or times out.
    """
     
    url = f"{REGION_SPECIFIC_RELEVANCE_BASE_URL}/studios/{studio_id}/async_poll/{job_id}"

    headers = {
        'Authorization': RELEVANCE_AUTHORIZATION_TOKEN
    }

    for _ in range(MAX_POLL_ATTEMPTS):
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            status = response.json()           
            
            if status['type'] == 'complete':
                for update in status.get('updates', []):
                    if update['type'] == 'chain-success':
                        return update['output']['output']
            
            time.sleep(POLL_DELAY)
        except requests.exceptions.RequestException as e:
            print(f"An error occurred while polling: {e}")
            return None
    
    print("Max polling attempts reached without success")
    return None

@csrf_exempt
def chat_completions(request):
    # verify method
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)
    
    # make json pythonable
    try:
        # Assuming the POST data is sent as JSON
        request_data = json.loads(request.body)

    except json.JSONDecodeError:
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid JSON in request body'
            }, status=400)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)
    
    # get the relevance_agent_id (passed as model)
    relevance_agent_id = request_data.get('model')
    relevance_conversation_id = "1234"    
    
    # persist relevance_agent_id to database   
    conversation = models.Conversation(
        relevance_agent_id=relevance_agent_id,
        relevance_conversation_id = "1234"
    )

    conversation.save()

    # get the user content from the messages
    user_content = next((m['content'] for m in reversed(request_data.get('messages', [])) if m['role'] == 'user'), None)

    if not user_content:
        return JsonResponse({"error": "No user message found"}, status=400)
    
    job = trigger_agent(relevance_agent_id, user_content)
    if not job:
        return JsonResponse({"error": "Failed to trigger agent"}, status=500)

    job_response = job.content
    job_response = json.loads(job_response.decode('utf-8'))

    # update record
    relevance_conversation_id = job_response['conversation_id']

    models.Conversation.objects.filter(relevance_conversation_id='1234').update(relevance_conversation_id=relevance_conversation_id)    
    
    studio_id = job_response['job_info'].get('studio_id')
    job_id = job_response['job_info'].get('job_id')
    
    if not studio_id or not job_id:
        return JsonResponse({"error": "Missing studio_id or job_id in response"}, status=500)
    
    agent_response = poll_for_updates(studio_id, job_id)

    if not agent_response:
        return JsonResponse({"error": "Failed to get agent response after polling"}, status=500)
    
    latest_response = agent_response.get('answer', '')

    def generate():
        """
        Generator function to stream the response word by word.

        Yields:
            str: JSON-formatted string containing each word of the response.
        """
        words = latest_response.split()
        for word in words:
            json_data = json.dumps({
                'choices': [
                    {
                        'delta': {
                            'content': word + ' ',
                            'role': 'assistant'
                        }
                    }
                ]
            })
            yield f"data: {json_data}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingHttpResponse(generate(), content_type='text/event-stream')


   
    

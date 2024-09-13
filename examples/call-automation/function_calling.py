import enum
import logging
from typing import Annotated,Optional

from dotenv import load_dotenv
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.agents.voice_assistant import VoiceAssistant
from livekit.plugins import deepgram, openai, silero, elevenlabs, cartesia, azure
from datetime import datetime
from bson import ObjectId
from db import collection, bookings_collection
load_dotenv()
import json
from pydantic import BaseModel

logger = logging.getLogger("function-calling-demo")
logger.setLevel(logging.INFO)

# not working with pydantic, livekit prefers premitives and Enum
class UpdateDict(BaseModel):
    visit_type: str
    reason_for_the_visit : str
    name : str
    date_of_birth : str
    mobile_number : str
    insurance_name : str
    appointment_date : str
    appointment_start_time : str
    appointment_end_time: str
    

class VisitType(enum.Enum):
    # ai_callable can understand enum types as a set of choices
    # this is equivalent to:
    #     `Annotated[Room, llm.TypeInfo(choices=["bedroom", "living room", "kitchen", "bathroom", "office"])]`
    FOLLOW_UP = "follow up"
    WALK_IN = "walk in"
    CONSULTATION = "consultation"
    VIRTUAL_CONSULTATION = "telemedicine"



class AssistantFnc(llm.FunctionContext):
    """
    The class defines a set of AI functions that the assistant can execute.
    """

    def __init__(self) -> None:
        super().__init__()

    
    def update_slots_availability(self,date_str, start_time_str, end_time_str, flag:bool=False):
        logger.info(f"update_slots_availability - {date_str} {start_time_str} {end_time_str}")
        # Find the calendar entry for the specific date
        
        calendar_entry = collection.find_one({"_id": date_str},)
        
        if not calendar_entry:
            logger.info(f"No calendar entry found for {date_str}")
            return 

        # Iterate through the slots and update the availability for the relevant slots
        for slot in calendar_entry['slots']:
            if slot['start_time'] >= start_time_str and slot['end_time'] <= end_time_str:
                slot['availability'] = flag

        # Update the document in MongoDB
        collection.update_one({"_id": date_str}, {"$set": {"slots": calendar_entry['slots']}})
        print(f"Updated availability for slots between {start_time_str} and {end_time_str} on {date_str}")

        return 
    
    @llm.ai_callable(description="To Cancel the Appointment with a given booking id")
    async def cancel_appointment(self,
                               booking_id: Annotated[str, llm.TypeInfo(description="Booking ID of the appointment to cancel")],
                               ):
        logger.info(f"Cancellation Requested for Booking ID {booking_id}")
        try:
            # Ensure record_id is converted to ObjectId if it's not already
            if isinstance(booking_id, str):
                booking_id = ObjectId(booking_id)
            
            # Perform the delete operation
            result = bookings_collection.delete_one({"_id": booking_id})
            
            if result.deleted_count > 0:
                return f"Booking ID {booking_id} has been successfully Cancelled."
            else:
                return f"Couldn't find any appointment with above booking id {booking_id}, cancellation request is unsuccessful loop in a human"
        
        except Exception as e:
            f"An error occurred while processing the cancellation request, connect to the human"

    
        
    @llm.ai_callable(description="Look up for the Appointment slots with Doctor Trinka")
    async def get_appointments(self,
                               date: Annotated[str, llm.TypeInfo(description="The date in dd-mm-yyyy format")],
                               morning: Annotated[bool, llm.TypeInfo(description="If there existing any preference in the morning slots")]= False,
                               evening: Annotated[bool, llm.TypeInfo(description="If there existing any preference in the evening slots")] = False,
                               ):
        
        
        try:
            logger.info("get_appointment - date: %s", date)
            result = collection.find_one(
                {"_id": date},  # Match the document by the given date
                # {"slots":{"$elemMatch": {"availability": True},"$slice": 5}}
                # {"slots": {"$elemMatch": {"availability": True},"$slice": 5}}  # Limit the slots to 5 results
            )
            if result:
                if morning or evening:
                    if result and "slots" in result:
                        available_slots = [slot for slot in result['slots'] if slot['availability'] and (morning and slot['start_time'] < "13:00") or 
                            (evening and slot['start_time'] >= "12:00")]
                        result_unpacked = available_slots  # Limit to the first 5 available slots
                        logger.info(f"Got following results with preferences morning {morning} evening {evening} {result_unpacked}")
                else:
                    if result and "slots" in result:
                        available_slots = [slot for slot in result['slots'] if slot['availability']]
                        result_unpacked = available_slots#[:3] # Limit to the first 5 available slots
                    else:
                        result_unpacked = []

                # result_unpacked = result.get('slots', [])
                    logger.info(f"Got following results with no preferences {result_unpacked}")
                return f"Following Slots are available {result_unpacked}"
            else:
                return f"No slots available for the given day"

        except Exception as e:
            logger.info(f"Error {e}")
            # print(e)
            return f"am having trouble right now, will forward to our super great manager to assist" 
    
    @llm.ai_callable(description="Book an Appointment with Doctor Trinka")    
    async def book_appointment(self, 
                               visit_type : Annotated[VisitType,llm.TypeInfo(description="Type of the visit")],
                               reason_for_the_visit : Annotated[str,llm.TypeInfo(description="Reason for the visit")],
                               name : Annotated[str,llm.TypeInfo(description="Name of the Patient")],
                               date_of_birth :Annotated[str, llm.TypeInfo(description="The date of birth of the patient in dd-mm-yyyy format")], 
                               mobile_number :Annotated[str, llm.TypeInfo(description="Valid Mobile Number of patient")],
                               insurance_name : Annotated[str, llm.TypeInfo(description="Patient Insurance Firm Information")], 
                               appointment_date : Annotated[str, llm.TypeInfo(description="The date of the appointment in dd-mm-yyyy format")],
                               appointment_start_time : Annotated[str, llm.TypeInfo(description="Appointment start time in HH:MM format")],
                               appointment_end_time: Annotated[str, llm.TypeInfo(description="Appointment start time in HH:MM format")],
                               ):
    
        booking_data = {
        "visit_type": visit_type,
        "reason_for_the_visit": reason_for_the_visit,
        "name": name,
        "date_of_birth": date_of_birth,
        "mobile_number": mobile_number,
        "insurance_name": insurance_name,
        "appointment_date": appointment_date,
        "appointment_start_time": appointment_start_time,
        "appointment_end_time": appointment_end_time
        }
        
        result = bookings_collection.insert_one(booking_data)
        self.update_slots_availability(appointment_date, appointment_start_time, appointment_end_time)

        logger.info(f"Successfully Booked an appointment for {appointment_start_time}-{appointment_end_time} with details {reason_for_the_visit}-{name}-{date_of_birth}-{mobile_number}-{insurance_name} and database _id {result.inserted_id}")
        return f"Successfully Booked an appointment for {appointment_start_time}-{appointment_end_time} with details {reason_for_the_visit}-{name}-{date_of_birth}-{mobile_number}-{insurance_name} and booking_id {result.inserted_id}"

    # @llm.ai_callable(description="modifies an appointment using booking _id from existing session after earlier booking is successful and needs to modify/correct its details ")    
    # async def modify_appointment(self,
    #                              _id: Annotated[str,llm.TypeInfo(description="Apointment Booking ID from earlier successful appoinment from current session")],
    #                              update_dict: Annotated[UpdateDict,llm.TypeInfo(description="Dictionary containing updated keys and values to modify")]
    #                              ):
    #     update_dict = json.loads(update_dict)
    #     logger.log(f"modify_appointment {_id}-{update_dict}")
        
    #     try:
    #     # Ensure booking_id is converted to ObjectId if it's not already
    #         if isinstance(_id, str):
    #             booking_id = ObjectId(_id)
            
    #         # Use update_one to update the document
    #         result = bookings_collection.update_one(
    #             {"_id": booking_id},  # Filter by _id
    #             {"$set": update_dict}  # Use $set to update specific fields
    #         )
            
    #         if result.matched_count == 0:
    #             return f"No booking found with ID {booking_id}"
    #         elif result.modified_count > 0:
    #             return f"Booking with ID {booking_id} successfully updated"
            
        
    #     except Exception as e:
    #         return f"Could not modify the appointment details"


async def entrypoint(ctx: JobContext):
    fnc_ctx = AssistantFnc()  # create our fnc ctx instance

    async def _will_synthesize_assistant_reply(
        assistant: VoiceAssistant, chat_ctx: llm.ChatContext
    ):
        # Inject the current state of the lights into the context of the LLM
        chat_ctx = chat_ctx.copy()
        # chat_ctx.messages.append(
        #     llm.ChatMessage(
        #         content=(
        #             """
        #             Initial Context can be added from here
        #             """
        #             ),
        #         role="user",
        #     ))
        return assistant.llm.chat(chat_ctx=chat_ctx, fnc_ctx=assistant.fnc_ctx)

    initial_chat_ctx = llm.ChatContext()
    initial_chat_ctx.messages.append(
        llm.ChatMessage(
            content=(
               f'''
                YOU AREA AN AI IN THE MIDDLE OF A PHONE CALL, SPEAK NATURALLY, CONCISELY, CASUALLY WITH FILLER WORDS JUST LIKE A PERSON
                KEEP THE CONVERSATION ON TOPIC, ALWAYS TRY TO SIMPLIFY THE INFORMATION FOR THE LAYMEN CALLER
                SPELL OUT NUMBERS IN THEIR SPOKEN FORM, DON'T USE ANY TEXT FORMATTING AS YOU ARE INTERACTING OVER VOICE
                ADD FILLER WORDS to the response when interacting with the function calling
                NEVER READ OUT OR GIVE MORE THAN 3 OPTIONS TO THE USER
                
                Today's Date and Current Time is {datetime.utcnow()}
                - You are a Texas Health Front Desk assistant 
                - located at Downtown Houston 10XB 10051
                - Paid Parking is available at 2nd Floor
                
                Your interface with callers in voice, Input will be from ASR System which might have some transcription mistakes, but your output is 100% correct 
                You should use short and concise responses, and avoiding usage of unpronouncable punctuation and 
                Generate the content in readable manner and non technical manner
                Handle ambuiguities with a confirmation
                APPOINTMENT BOOKING FLOW : Ask for reason they called, any prefered date, look for available slots, then go ahead with booking the appointment with appropriate details in sequential manner
                Ask whatever details needed in sequential manner, don't bother user with data format specifics, keep the conversation naturally sounding
                Always try inform the caller when using functions as there might be awkward pauses due to latencies associated with API calls, so please inform like : umm, give me a moment please etc
                
                Example of Asking Questions
                Context : If you need mutiple details like date of birth, name, phone number always ask them in sequential manner, Ideal response is asking details one at time
                
                Example for Simplifying conversation
                - If there are multiple available appointment slots 10 AM - 11 AM, 11 AM - 12 PM, 12 PM - 1 PM
                - Ideal response is : we have available slots between 10 AM to 1 PM, when do you prefer
                - explaination - we are consolidating the information ideally when talking to a person
                
                Example of conversation with filler words
                - Patient: Uh, hi, I, um, I have a, uh, appointment today with Dr. Lewis, I think?
                - Agent: Oh, okay, sure, let me just, uh, check that for you. Can I get your, um, name please?
                - Patient: Yeah, it's Sarah Wilson.
                - Agent: Alright, Sarah, um, give me just a sec… okay, I see you have an appointment at, uh, 10:30 with Dr. Lewis. Is that right?
                - Patient: Yeah, I think so. Uh, but I was wondering, like, um, is she running on time today? 'Cause, uh, I kinda have to leave by noon.
                - Agent: Right, um, let me just, uh, check that for you... okay, so it looks like Dr. Lewis is running just, um, about 10 minutes behind. But, uh, you should still be able to finish up before noon.
                - Patient: Oh, cool, um, that works. Do I just, uh, wait here, or…?
                - Agent: Yeah, so, um, you can take a seat in the waiting area, and we'll, uh, call you when she's ready.
                - Patient: Alright, great, um, thanks!
                - Agent: You're welcome! Uh, let us know if you need anything else.

                If caller is calling for an emergency condition, please forward it to human by generating FORWARDING_TO_HUMAN
                
                Always ask if needs help with anything before ending the conversation
                '''
            ),
            role="system",
        )
    )

    assistant = VoiceAssistant(
        vad=silero.VAD.load(),
        stt=deepgram.STT(),
        llm=openai.LLM(model="gpt-4o-2024-08-06"),
        tts=openai.TTS(voice="shimmer"),
        # tts=cartesia.TTS(voice="00a77add-48d5-4ef6-8157-71e5437b282d"),    
        # tts=azure.TTS(voice="en-US-DustinMultilingualNeural",),
        fnc_ctx=fnc_ctx,
        chat_ctx=initial_chat_ctx,
        will_synthesize_assistant_reply=_will_synthesize_assistant_reply,
    )

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Start the assistant. This will automatically publish a microphone track and listen to the first participant
    # it finds in the current room. If you need to specify a particular participant, use the participant parameter.
    assistant.start(ctx.room)

    await assistant.say("Welcome to Texas Health, how can I help you today?")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))

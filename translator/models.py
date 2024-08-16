from django.db import models

class Conversation(models.Model):
    relevance_agent_id = models.CharField(max_length=100)
    relevance_conversation_id = models.CharField(max_length=100, default='1234')
   

    def __str__(self):
        return f"Relevance Conversation ID {self.relevance_conversation_id} with Relevance Agent ID {self.relevance_agent_id}"

    class Meta:
        ordering = ['-relevance_conversation_id']

    @classmethod
    def remove_all(cls):
        cls.objects.all().delete()
        return f"All {cls.__name__} records have been deleted."
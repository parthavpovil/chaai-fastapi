# Bugfix Requirements Document

## Introduction

This document specifies the requirements for fixing the websocket broadcasting inconsistency where AI assistant messages are not appearing in real-time on the workspace owner's dashboard. Currently, user messages from Telegram appear in real-time via websocket, but AI assistant responses do NOT appear in real-time. The workspace owner must manually refresh or call the get conversation API to see assistant messages.

The root cause is that websocket broadcasting via `notify_new_message()` is inconsistently applied after creating assistant messages. Some code paths call it (RAG responses), while others don't (escalation acknowledgments, error messages, business hours messages, AI agent responses).

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN an escalation acknowledgment message is created in `escalation_router.py` line 116 (`send_customer_acknowledgment()`) THEN the system does not broadcast the message via websocket to the workspace owner's dashboard

1.2 WHEN an error message for blocked contacts is created in `message_processor.py` line 485 THEN the system does not broadcast the message via websocket to the workspace owner's dashboard

1.3 WHEN a business hours auto-reply message is created in `message_processor.py` line 517 THEN the system does not broadcast the message via websocket to the workspace owner's dashboard

1.4 WHEN an AI agent response is created in `webhooks.py` line 450 THEN the system does not broadcast the message via websocket to the workspace owner's dashboard

1.5 WHEN an AI agent response is created in `webchat.py` line 496 THEN the system does not broadcast the message via websocket to the workspace owner's dashboard

### Expected Behavior (Correct)

2.1 WHEN an escalation acknowledgment message is created in `escalation_router.py` THEN the system SHALL immediately broadcast the message via `notify_new_message()` so workspace owners see it in real-time

2.2 WHEN an error message for blocked contacts is created in `message_processor.py` THEN the system SHALL immediately broadcast the message via `notify_new_message()` so workspace owners see it in real-time

2.3 WHEN a business hours auto-reply message is created in `message_processor.py` THEN the system SHALL immediately broadcast the message via `notify_new_message()` so workspace owners see it in real-time

2.4 WHEN an AI agent response is created in `webhooks.py` THEN the system SHALL immediately broadcast the message via `notify_new_message()` so workspace owners see it in real-time

2.5 WHEN an AI agent response is created in `webchat.py` THEN the system SHALL immediately broadcast the message via `notify_new_message()` so workspace owners see it in real-time

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a RAG response is created in `webhooks.py` (line 519-548) THEN the system SHALL CONTINUE TO broadcast the message via `notify_new_message()` as it currently does

3.2 WHEN a RAG response is created in `webchat.py` (line 533-565) THEN the system SHALL CONTINUE TO broadcast the message via `notify_new_message()` as it currently does

3.3 WHEN a user message is received from any channel (Telegram, WhatsApp, webchat) THEN the system SHALL CONTINUE TO broadcast the message via websocket in real-time as it currently does

3.4 WHEN `notify_new_message()` is called THEN the system SHALL CONTINUE TO use the Redis pub/sub mechanism to broadcast across multiple workers as it currently does

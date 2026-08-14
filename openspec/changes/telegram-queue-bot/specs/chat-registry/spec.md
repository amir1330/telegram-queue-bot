## ADDED Requirements

### Requirement: Register chats and lessons
The system SHALL persist every chat that configures lessons, along with the chat's lessons and their settings, using chat id as the key.

#### Scenario: Chat gains its first lesson
- **WHEN** a chat admin configures the first lesson for that chat
- **THEN** the system records the chat and its lesson so the bot can restore state after a restart

#### Scenario: Lesson data persists
- **WHEN** the bot restarts with previously configured lessons
- **THEN** the system can enumerate all chats and lessons from the database

### Requirement: Persist queue sessions
The system SHALL persist each open queue session's active message reference so the bot can resume live-editing and cleanup after a restart.

#### Scenario: Open session survives restart
- **WHEN** the bot restarts while a queue session is open
- **THEN** the system can retrieve the session's active message id and continue to update it

### Requirement: Persist queue entries
The system SHALL persist individual queue entries with their chat, lesson, session date, user id, display name, and join time.

#### Scenario: Entries survive restart
- **WHEN** the bot restarts while entries exist in a queue
- **THEN** the queue still contains those entries, in the same order
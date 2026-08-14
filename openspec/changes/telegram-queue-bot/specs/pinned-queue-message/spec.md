## ADDED Requirements

### Requirement: Single pinned message per session
The system SHALL maintain exactly one pinned message per chat-lesson-session, stored in the database, so enablement of a session never posts a second pinned queue message.

#### Scenario: Open posts once
- **WHEN** a queue session is opened
- **THEN** the system posts a single "Queue is open!" message, pins it silently, and records the message id for that session

#### Scenario: Open never reposts for same session
- **WHEN** a session is already open and the open job logic runs again
- **THEN** the system reuses the existing message instead of posting a new pinned message

### Requirement: Live-edit queue message
The system SHALL update the pinned queue message in place whenever the queue changes, instead of posting a new message.

#### Scenario: Join updates the pinned message
- **WHEN** a user joins the queue
- **THEN** the system edits the session's pinned message to reflect the new queue

#### Scenario: Leave updates the pinned message
- **WHEN** a user leaves the queue
- **THEN** the system edits the session's pinned message to reflect the updated queue

#### Scenario: Close updates the pinned message
- **WHEN** a session closes
- **THEN** the system edits the session's pinned message to show a closed indicator

### Requirement: Pins silently
The system SHALL pin queue messages silently (notifications disabled) to avoid spamming the chat.

#### Scenario: Silent pin
- **WHEN** the system pins the queue open message
- **THEN** the pin is performed with notifications disabled
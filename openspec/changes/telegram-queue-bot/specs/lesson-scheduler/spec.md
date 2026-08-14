## ADDED Requirements

### Requirement: Auto-open queue before lesson
The system SHALL automatically open a chat's queue for a lesson at `lesson_time − open_before_min`.

#### Scenario: Queue opens before lesson
- **WHEN** the scheduled open time for a lesson is reached
- **THEN** the system creates a session for today, posts a "Queue is open!" message, pins it silently, and starts accepting `/queue` entries

#### Scenario: Queue opens before lesson (same-day)
- **WHEN** the open time is reached on a different date than the lesson (e.g. lesson at 00:10 opened the prior day)
- **THEN** the system assigns the lesson's session date (the date the lesson actually occurs)

### Requirement: Auto-close queue at lesson time
The system SHALL automatically close a chat's lesson queue at the exact lesson time, stopping new entries and marking the queue message as closed.

#### Scenario: Queue closes at lesson time
- **WHEN** the scheduled close time for a lesson is reached
- **THEN** the system stops accepting `/queue` entries for that session and edits the pinned message to show it is closed (🔒)

#### Scenario: Join after close is rejected
- **WHEN** a user runs `/queue` after the lesson's queue has closed
- **THEN** the system rejects the command and replies that the queue is closed

### Requirement: Auto-cleanup after lifetime
The system SHALL clean up a lesson session at `lesson_time + lifetime_min`: unpin and delete the queue message, clear the session's queue entries, and remove the stored active message.

#### Scenario: Session cleaned up after lifetime
- **WHEN** the scheduled cleanup time for a lesson is reached
- **THEN** the system unpins and deletes the queue message, clears that session's queue entries, and removes the active message record

### Requirement: Restart-safe job registration
The system SHALL re-register scheduler jobs for all persisted lessons on bot startup, so scheduling survives restarts and redeploys.

#### Scenario: Bot restarts mid-cycle
- **WHEN** the bot starts up and there are persisted lessons
- **THEN** the system re-creates each lesson's open, close, and cleanup jobs from the database

#### Scenario: Cleanup job runs after restart for open session
- **WHEN** the bot restarts while a session is open and the cleanup time has already passed
- **THEN** the system cleans up that stale session on startup

### Requirement: Jobs are per-chat and per-lesson
The system SHALL schedule, open, close, and clean up queues independently for each chat and each lesson, using predictable job identifiers.

#### Scenario: Two chats isolate their schedules
- **WHEN** two chats have lessons at the same time
- **THEN** the system opens, closes, and cleans up each chat's queue independently without cross-chat interaction
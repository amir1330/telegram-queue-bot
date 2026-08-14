## ADDED Requirements

### Requirement: Join the queue
The system SHALL add a user to today's open queue for their chat when the user runs `/queue`, and SHALL reject the attempt if the user is already in the queue or the queue is not open.

#### Scenario: User joins an open queue
- **WHEN** a user runs `/queue` and an open queue exists for today's session
- **THEN** the system adds the user to the queue at the next available position and confirms the join

#### Scenario: User already in queue
- **WHEN** a user who is already in the queue runs `/queue` again
- **THEN** the system rejects the duplicate and informs the user they are already in the queue

#### Scenario: Queue not open
- **WHEN** a user runs `/queue` before the open time, after close, or with no lesson scheduled today
- **THEN** the system rejects the join and explains the queue is not open

### Requirement: Leave the queue
The system SHALL remove a user from the queue when they run `/leave`, shifting remaining users up, and SHALL inform the user if they are not in the queue.

#### Scenario: User leaves the queue
- **WHEN** a user in the queue runs `/leave`
- **THEN** the system removes the user and shifts subsequent users up by one position

#### Scenario: User not in queue leaves
- **WHEN** a user who is not in the queue runs `/leave`
- **THEN** the system informs the user they are not in the queue

### Requirement: List the queue
The system SHALL display the current queue for the chat when `/list` is run, showing each entry's position and display name.

#### Scenario: List shows entries in order
- **WHEN** a user runs `/list` and the queue has entries
- **THEN** the system shows a numbered list of the queue entries in join order

#### Scenario: List is empty
- **WHEN** a user runs `/list` and the queue has no entries
- **THEN** the system shows an empty-queue message

### Requirement: Report position privately
The system SHALL privately reply to a user with their position in the queue when they run `/myposition`.

#### Scenario: User asks for their position
- **WHEN** a user in the queue runs `/myposition`
- **THEN** the system sends a private reply with the user's position in the queue

#### Scenario: User not in queue asks position
- **WHEN** a user not in the queue runs `/myposition`
- **THEN** the system privately replies that the user is not in the queue

### Requirement: Per-chat scope
Backend queue state SHALL be scoped by chat, so queues in different chats never mix.

#### Scenario: Entries isolated between chats
- **WHEN** two chats have simultaneous queues
- **THEN** each chat's queue contains only entries made in that chat
## ADDED Requirements

### Requirement: Configure lessons per chat
The system SHALL allow a chat administrator to create or update a lesson for their chat by specifying a day of the week (mon–sun) and a time (HH:MM), and SHALL allow removing an existing lesson by day of week.

#### Scenario: Admin sets a lesson
- **WHEN** a chat administrator runs `/setlesson Monday 23:00`
- **THEN** the system stores a lesson for that chat on Monday at 23:00

#### Scenario: Admin updates an existing lesson
- **WHEN** a chat administrator runs `/setlesson Monday 22:30` and a Monday lesson already exists for that chat
- **THEN** the system updates the existing lesson's time to 22:30 instead of creating a duplicate

#### Scenario: Admin removes a lesson
- **WHEN** a chat administrator runs `/removelesson Monday`
- **THEN** the system deletes that chat's Monday lesson and its scheduled jobs

#### Scenario: Non-admin config is rejected
- **WHEN** a non-admin user runs `/setlesson`
- **THEN** the system rejects the command and replies that only admins can configure

### Requirement: Configure lesson window settings
The system SHALL allow a chat administrator to set the open-before window (minutes before lesson time the queue opens) and the lifetime window (minutes after lesson start before cleanup) for the last-edited lesson.

#### Scenario: Admin sets open-before window
- **WHEN** a chat administrator runs `/setopenbefore 30`
- **THEN** the system updates the last-edited lesson's open-before to 30 minutes

#### Scenario: Admin sets lifetime window
- **WHEN** a chat administrator runs `/setlifetime 60`
- **THEN** the system updates the last-edited lesson's lifetime to 60 minutes

#### Scenario: Defaults are applied
- **WHEN** a lesson is created without explicit window settings
- **THEN** the system uses open-before 30 minutes and lifetime 60 minutes

### Requirement: List configured lessons
The system SHALL allow a chat administrator to view all lessons configured for their chat.

#### Scenario: Admin lists lessons
- **WHEN** a chat administrator runs `/mylessons`
- **THEN** the system replies with the chat's configured lessons, their days, times, and window settings

#### Scenario: No lessons exist
- **WHEN** a chat administrator runs `/mylessons` and the chat has no configured lessons
- **THEN** the system replies that no lessons are configured

### Requirement: Config changes apply immediately
The system SHALL apply lesson configuration changes to the scheduler immediately, without requiring a bot restart.

#### Scenario: Lesson added while running
- **WHEN** a chat administrator adds a lesson for an upcoming day
- **THEN** the system registers the corresponding scheduler jobs for that lesson right away

#### Scenario: Lesson removed while running
- **WHEN** a chat administrator removes a lesson
- **THEN** the system removes that lesson's scheduler jobs right away
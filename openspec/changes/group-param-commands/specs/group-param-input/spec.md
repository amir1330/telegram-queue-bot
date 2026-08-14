## Purpose

Collects parameters for group-chat bot commands without mixing up users: either from inline arguments on the command line, or from a selective ForceReply prompt bound to that chat and user.

## ADDED Requirements

### Requirement: Dual input for parametric commands
The system SHALL accept parameters for `/setname`, `/setlesson`, `/before`, `/duration`, and `/delete` either as arguments on the command message or via a follow-up reply after a prompt. When arguments are present and valid for that command, the system MUST process the command immediately without prompting.

#### Scenario: One-shot setname with arguments
- **WHEN** a user sends `/setname Иван`
- **THEN** the system sets that user's display name to Иван and does not send a parameter prompt

#### Scenario: One-shot setlesson with arguments
- **WHEN** a chat administrator sends `/setlesson Monday 23:00`
- **THEN** the system stores or updates the Monday lesson at 23:00 and does not send a parameter prompt

#### Scenario: Bare command starts prompt flow
- **WHEN** a user sends `/setname` with no arguments
- **THEN** the system replies asking them to enter the name and waits for that user's follow-up

### Requirement: Selective ForceReply prompts
When starting a parameter prompt, the system SHALL reply with a message that asks for the needed parameter(s) and MUST attach `ForceReply` with `selective=True` so Telegram offers the reply UI only to the user who invoked the command.

#### Scenario: Bare setname prompts only the caller
- **WHEN** a user sends `/setname` in a group
- **THEN** the bot replies with a name prompt using selective ForceReply, and other group members are not prompted by Telegram's reply UI for that message

### Requirement: Pending state keyed by chat and user
The system SHALL store pending parameter collection keyed by the pair `(chat_id, user_id)` together with which command is waiting. A message from a different user in the same chat MUST NOT complete another user's pending prompt.

#### Scenario: Other user's message is ignored by the prompt
- **WHEN** user A has an active `/setname` prompt in a chat and user B sends a normal text message in that chat
- **THEN** the system does not treat B's message as A's name and leaves A's pending state unchanged

#### Scenario: Same user in another chat is independent
- **WHEN** user A has an active prompt in chat X and sends unrelated text in chat Y
- **THEN** the system does not complete the prompt in chat X from that message

### Requirement: Accept only matching follow-up replies
The system SHALL complete a pending prompt only when the message is from the same `(chat_id, user_id)` that owns the pending state and the message is a reply to the bot's prompt message (or otherwise clearly bound to that pending state for that user). After successful validation and apply, the system MUST clear that user's pending state.

#### Scenario: Reply to prompt completes setname
- **WHEN** user A has a pending `/setname` prompt and replies to the bot's prompt with `Иван`
- **THEN** the system sets A's display name to Иван and clears A's pending state for that chat

#### Scenario: Non-reply text does not steal the prompt
- **WHEN** user A has a pending `/setname` prompt and sends a new top-level text message that is not a reply to the prompt
- **THEN** the system does not apply that text as the name (pending state remains until a valid bound reply or cancellation)

### Requirement: Invalid follow-up keeps or clears safely
When a bound follow-up fails validation for the pending command, the system SHALL reply with an error (or usage hint) and MUST NOT apply partial invalid data. The system MAY keep the pending state so the user can reply again, or clear it and require re-invoking the command; either behavior MUST be consistent per command and MUST NOT apply another user's input.

#### Scenario: Invalid setlesson reply is rejected
- **WHEN** an admin has a pending `/setlesson` prompt and replies with text that is not a valid day and time
- **THEN** the system does not create or update a lesson and informs the user the input is invalid

### Requirement: Optional cleanup of prompt messages
After a pending prompt is completed successfully, the system MAY delete its intermediate prompt message in the group to reduce chat clutter. Failure to delete MUST NOT roll back the successful command result.

#### Scenario: Successful apply still wins if delete fails
- **WHEN** a user's follow-up is accepted and applied but deleting the prompt message fails
- **THEN** the command result remains applied and the pending state is still cleared

### Requirement: Admin gates still apply before prompting
For admin-only parametric commands (`/setlesson`, `/before`, `/duration`, `/delete`), the system SHALL enforce admin (and existing bot-rights checks where applicable) before starting a prompt. Non-admins MUST be rejected without creating pending state.

#### Scenario: Non-admin bare setlesson is rejected
- **WHEN** a non-admin user sends `/setlesson` with no arguments
- **THEN** the system rejects the command as admin-only and does not start a ForceReply prompt for that user

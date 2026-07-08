from commands import ClickCommand, JumpCommand, PrintBoardCommand, WaitCommand
from handlers.click import handle_click
from handlers.jump import handle_jump
from handlers.print_board import handle_print_board
from handlers.wait import handle_wait

COMMAND_HANDLERS = {
    ClickCommand: lambda state, cmd, output: handle_click(state, cmd.x, cmd.y),
    JumpCommand: lambda state, cmd, output: handle_jump(state, cmd.x, cmd.y),
    WaitCommand: lambda state, cmd, output: handle_wait(state, cmd.ms),
    PrintBoardCommand: lambda state, cmd, output: handle_print_board(state, output),
}

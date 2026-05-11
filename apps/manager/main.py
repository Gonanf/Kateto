from modules.core.server import Manager
from modules.core.prompt import PromptFunction

manager = Manager(PromptFunction).serve()

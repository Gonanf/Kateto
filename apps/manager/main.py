from modules.server import Manager
from modules.prompt import PromptFunction

manager = Manager(PromptFunction).serve()

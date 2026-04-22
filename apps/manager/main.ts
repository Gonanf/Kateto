import { createOpencode, createOpencodeClient, type Session } from "@opencode-ai/sdk"
import { Effect, Layer, Context } from "effect"

enum Agents {
  Charlatan = "kateto-charlatan",
  Soñador = "kateto-soñador"
}



// TODO: Put this in an Effect and fork it
const opencode = await (async () => {
  try {
    console.log("Creating the server...")
    return await createOpencode({
      hostname: "127.0.0.1",
      port: 4096,
      config: {
        model: "opencode-go/qwen3.5-plus"
      }
    })
  } catch {
    console.log("A server already exists, connecting...")
    const client = createOpencodeClient({
      baseUrl: "http://127.0.0.1:4096"
    })
    return { client, server: null }
  }
})()


class SessionService extends Context.Tag("SessionService")<SessionService, Session>() { }

const useSession = Layer.effect(SessionService, Effect.gen(function* () {
  console.log("Creating session...")
  const session = yield* Effect.tryPromise({ try: () => opencode.client.session.create(), catch: (error) => new Error(`No se pudo crear la sesion: ${error}`) })
  if (session.error) return yield* Effect.fail(session.error)
  console.log("Created the session service with id", session.data.id)
  return session.data
}))


const sendChat = (prompt: string, agent: Agents) => Effect.gen(function* () {
  const session = yield* SessionService

  console.log("Sending prompt to ", agent)
  const response = yield* Effect.tryPromise({
    try: () => opencode.client.session.prompt({
      path: { id: session.id },
      body: {
        parts: [{ type: "text", text: prompt }],
        agent: agent.toString()
      }
    }),
    catch: (error) => new Error(`Cannot send prompt: ${error}`)
  })

  if (response.error) return yield* Effect.fail(response.error)
  return response.data
}
)


const program = Effect.gen(function* () {
  console.log("Sending prompt...")
  const response = yield* sendChat("Call me a good boy", Agents.Charlatan)

  console.log(response)
  for (const part of response.parts) {
    console.log(part)
  }

})

console.log("Starting")
console.log(
  await Effect.runPromise(
    program.pipe(
      Effect.provide(useSession)
    )
  )
)

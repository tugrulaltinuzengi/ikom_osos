// Upload a profile to a gateway: the profile_begin/regs/meta/commit sequence, one
// acked step at a time. The first refusal stops the upload; the gateway keeps its
// previous profile because nothing replaces it before profile_commit succeeds.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./profile.js"));
  else root.OsosUploader = factory(root.OsosProfile);
})(typeof self !== "undefined" ? self : this, function (P) {
  "use strict";

  class UploadError extends Error {
    constructor(message, step, action) { super(message); this.step = step; this.action = action; }
  }

  // After a lost ack the same chunk is sent again. If the gateway had in fact
  // applied it, it refuses the repeat with "expected index N" / "expected offset N"
  // where N is exactly where we are going next - so that refusal means "already done".
  function alreadyApplied(action, args, detail) {
    const m = /expected (index|offset) (\d+)/.exec(detail || "");
    if (!m) return false;
    const next = parseInt(m[2], 10);
    if (action === "profile_regs") return m[1] === "index" && next === args.i + args.regs.length;
    if (action === "profile_meta") return m[1] === "offset" && next === args.off + args.data.length;
    return false;
  }

  // send(action, args) -> Promise<{ok, detail}|null>   (null == no answer in time)
  async function upload(profile, send, opts) {
    opts = opts || {};
    const errors = P.errorsOf(P.validate(profile));
    if (errors.length) throw new UploadError("profile has errors: " + errors[0].msg, 0, "validate");
    const cmds = P.wireCommands(profile);
    const total = cmds.length + (opts.assign ? 1 : 0);
    const retries = opts.retries === undefined ? 2 : opts.retries;
    const log = [];

    const step = async (i, action, args) => {
      let ack = null;
      let lostAck = false;
      for (let attempt = 0; attempt <= retries; attempt++) {
        if (opts.signal && opts.signal.aborted) throw new UploadError("cancelled", i, action);
        ack = await send(action, args);
        if (ack) break;
        lostAck = true;
      }
      if (!ack) throw new UploadError("the gateway did not answer " + action, i, action);
      // A commit whose ack was lost succeeded if the profile is now stored: the repeat
      // is refused with "no upload in progress" because there is nothing left to commit.
      if (!ack.ok && lostAck && action === "profile_commit" && /no upload in progress/.test(ack.detail || "") &&
          opts.verifyStored && await opts.verifyStored(profile)) {
        ack = { ok: true, detail: "stored (confirmed after a lost reply)" };
      }
      if (!ack.ok && !alreadyApplied(action, args, ack.detail)) throw new UploadError(ack.detail || "refused", i, action);
      log.push({ action, detail: ack.detail });
      if (opts.onProgress) opts.onProgress(i + 1, total, action, ack.detail);
      return ack;
    };

    for (let i = 0; i < cmds.length; i++) await step(i, cmds[i][0], cmds[i][1]);
    if (opts.assign) {
      await step(cmds.length, "profile_assign", { analyzer: opts.assign.analyzer, profile: profile.id });
    }
    return log;
  }

  return { upload, UploadError, alreadyApplied };
});

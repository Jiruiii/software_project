/* Drafts last for this tab. Course room tokens change each time someone re-enters. */
const classroomDrafts = (() => {
  const root='classroom.draft.';
  const prefix=(...parts)=>root+parts.map(encodeURIComponent).join(':')+':';
  function clear(start=root) {
    for(const key of Object.keys(sessionStorage)) if(key.startsWith(start)) sessionStorage.removeItem(key);
  }
  function key(room,activity,kind,id='') {
    const identity=room.course && room.uid
      ? [room.uid,room.course,room.enrollment || room.role]
      : ['session',room.token];
    return prefix(...identity,activity,kind)+encodeURIComponent(id);
  }
  function read(key) {
    try {return JSON.parse(sessionStorage.getItem(key));}
    catch {sessionStorage.removeItem(key); return null;}
  }
  return {key,read,clear,clearMembership(uid,course,enrollment) {clear(prefix(uid,course,enrollment));}};
})();

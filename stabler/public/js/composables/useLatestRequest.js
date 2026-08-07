// Guards an async loader against out-of-order responses. Each call takes a
// ticket before its await; only the newest ticket may write. A loader that
// writes shared state after an await without this will happily let a slow
// response for the previously selected record overwrite the current one.
export function useLatestRequest() {
	let seq = 0;
	return {
		// Take a ticket. Returns a predicate: true only while this is the newest.
		take() {
			const id = ++seq;
			return () => id === seq;
		},
		// Retire every in-flight ticket without issuing one (deselect / company switch).
		invalidate() {
			seq += 1;
		},
	};
}

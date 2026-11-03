// The names LeetCode's own judge has ready for a JavaScript or TypeScript answer written there, which it
// imports nowhere: a heap, a deque and lodash. Node preloads this file for every run (runner/runner.py), and
// each name is a getter, so a run that never asks for one pays nothing for it (lodash alone is half a megabyte
// of source). A name the answer declares itself shadows the one here, and assigning to it replaces it.
"use strict";

const lazy = (name, load) => {
  if (name in globalThis) return;
  let value;
  Object.defineProperty(globalThis, name, {
    configurable: true,
    get() {
      if (value === undefined) {
        try {
          value = load();
        } catch (e) {
          return undefined;   // the package is not in this image: the run fails as it would have anyway
        }
      }
      return value;
    },
    set(given) {
      Object.defineProperty(globalThis, name, { value: given, writable: true, configurable: true });
    },
  });
};

for (const name of ["PriorityQueue", "MinPriorityQueue", "MaxPriorityQueue"]) {
  lazy(name, () => require("@datastructures-js/priority-queue")[name]);
}
lazy("Deque", () => require("@datastructures-js/deque").Deque);
lazy("_", () => require("lodash"));

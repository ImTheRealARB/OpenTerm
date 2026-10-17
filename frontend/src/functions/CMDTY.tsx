import { Board } from "./Board";
import { CMDTY as DEF } from "./boards";
import type { FunctionProps } from "./registry";

export default function CMDTY(props: FunctionProps) {
  return <Board {...props} def={DEF} />;
}

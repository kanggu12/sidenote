// Built once when the runner image is made, only to fill the Go build cache that every Go compile starts from
// with the standard packages a solution or the example check uses (Go stopped shipping them compiled in 1.20, and
// compiling them again for each run took 4 s).
package main

import (
	"bufio"
	"bytes"
	"cmp"
	"container/heap"
	"container/list"
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"math"
	"math/big"
	"math/bits"
	"math/rand"
	"os"
	"reflect"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

var _ = bufio.NewReader
var _ = bytes.NewBuffer
var _ = cmp.Compare[int]
var _ = heap.Init
var _ = list.New
var _ = json.Marshal
var _ = errors.New
var _ = fmt.Println
var _ = maps.Keys[map[int]int]
var _ = math.Sqrt
var _ = big.NewInt
var _ = bits.OnesCount
var _ = rand.Intn
var _ = os.Stdout
var _ = reflect.ValueOf
var _ = regexp.MustCompile
var _ = slices.Sort[[]int]
var _ = sort.Ints
var _ = strconv.Itoa
var _ = strings.Split
var _ = time.Now
var _ = unicode.IsDigit
var _ = utf8.RuneLen

func main() {}

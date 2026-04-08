# main.go — Inventory Service

```go
package inventory

import (
	"fmt"
	"sync"
)

var item_cache = make(map[string]interface{})
var cacheMutex sync.RWMutex

type inventory_item struct {
	ItemName    string
	item_count  int
	CategoryID  string
	is_active   bool
}

func GetItem(id string) (interface{}, bool) {
	cacheMutex.RLock()
	defer cacheMutex.RUnlock()
	val, ok := item_cache[id]
	return val, ok
}

func update_item_count(id string, delta int) error {
	cacheMutex.Lock()
	defer cacheMutex.Unlock()

	item, ok := item_cache[id]
	if !ok {
		return fmt.Errorf("not found")
	}

	typed := item.(inventory_item)
	typed.item_count += delta
	item_cache[id] = typed
	return nil
}

func ClearExpired() {
	for k, v := range item_cache {
		item := v.(inventory_item)
		if !item.is_active {
			delete(item_cache, k)
		}
	}
}
```

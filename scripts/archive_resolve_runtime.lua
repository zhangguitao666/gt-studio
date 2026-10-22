-- Scope: generated media and newly-created timelines in the dedicated reference project only.
-- No preference changes, original media writes or user timeline edits.
local expected='REA Reference · 2026-10-21'
local media_path='/Users/zgt/agent/resolve-reconstruction/workspace/demo-media/motion.mp4'
local function quote(s)
 return '"'..tostring(s):gsub('[%z\1-\31\\"]',function(c)
  return ({['"']='\\"',['\\']='\\\\',['\n']='\\n',['\r']='\\r',['\t']='\\t'})[c] or string.format('\\u%04x',string.byte(c))
 end)..'"'
end
local function json(x)
 local t=type(x)
 if t=='nil' then return 'null' end
 if t=='string' then return quote(x) end
 if t=='boolean' or t=='number' then return tostring(x) end
 if t~='table' then return quote('<'..t..'>') end
 local keys={};for k,_ in pairs(x) do keys[#keys+1]=k end
 local array=#keys>0
 for _,k in ipairs(keys) do if type(k)~='number' then array=false end end
 local out={}
 if array then for i=1,#x do out[#out+1]=json(x[i]) end;return '['..table.concat(out,',')..']' end
 table.sort(keys,function(a,b)return tostring(a)<tostring(b)end)
 for _,k in ipairs(keys) do out[#out+1]=quote(k)..':'..json(x[k]) end
 return '{'..table.concat(out,',')..'}'
end
local p=resolve:GetProjectManager():GetCurrentProject()
assert(p and p:GetName()==expected,'Wrong reference project')
assert(type(REA_RUNTIME_PAYLOAD)=='string' and #REA_RUNTIME_PAYLOAD<524288,'No bounded original runtime payload retained')
local row={after={payload=REA_RUNTIME_PAYLOAD,payload_bytes=#REA_RUNTIME_PAYLOAD},timeline='REA_RUNTIME_API',completed=true}
local ok=p:GetCurrentTimeline():AddMarker(8,'Purple','REA_RUNTIME_API',json(row),1,json(row))
assert(ok,'Runtime payload marker not saved')
assert(resolve:GetProjectManager():SaveProject(),'Reference save failed')
print('REA_RUNTIME_ARCHIVED_BYTES='..#REA_RUNTIME_PAYLOAD)

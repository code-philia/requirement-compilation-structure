// Compiler-owned registration form. User types are published by the server from source rules.
import { useEffect, useState, useRef } from 'react';
import { Alert, Button, Card, Form, Input, Select } from '@arco-design/web-react';
interface Props {
  loginPath?: string;
  labels?: Partial<Record<'title'|'username'|'password'|'userType'|'submit'|'back', string>>;
}
export function RegisterPage({loginPath = '/login', labels = {}}: Props) {
  const words = {title:'注册账号',username:'账号',password:'密码',userType:'用户类型',submit:'注册',back:'返回登录',...labels};
  const [options, setOptions] = useState<{id:string;label:string}[]>([]);
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const posting = useRef(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const abort = new AbortController();
    void fetch('/api/auth/registration-options', {signal:abort.signal}).then(async response => {
      if (!response.ok) throw new Error('无法读取注册选项');
      const body = await response.json() as {enabled:boolean;userTypes:{id:string;label:string}[]};
      if (!abort.signal.aborted) {setEnabled(body.enabled);setOptions(body.userTypes);}
    }).catch(error => {if(!abort.signal.aborted)setError(String(error.message ?? error));})
      .finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return () => abort.abort();
  }, []);
  async function submit(values: {username:string;password:string;userType:string}) {
    if(posting.current)return;
    posting.current=true;
    setPending(true);setError('');
    try {
      const response = await fetch('/api/auth/register', {method:'POST',headers:{'content-type':'application/json'},
        body:JSON.stringify(values)});
      const body = await response.json();
      if(!response.ok)throw new Error(body.error ?? '注册失败');
      window.location.assign(loginPath);
    } catch(error) { setError(error instanceof Error ? error.message : String(error)); }
    finally {posting.current=false;setPending(false);}
  }
  return <main><Card title={words.title} loading={loading} style={{maxWidth:440,margin:'48px auto'}}>
    {error && <Alert type="error" content={error} />}
    {!loading && !enabled && <Alert type="info" content="当前系统未开放注册" />}
    {enabled && <Form layout="vertical" onSubmit={submit}>
      <Form.Item label={words.username} field="username" rules={[{required:true}]}><Input aria-label={words.username}/></Form.Item>
      <Form.Item label={words.password} field="password" rules={[{required:true}]}><Input.Password aria-label={words.password}/></Form.Item>
      <Form.Item label={words.userType} field="userType" rules={[{required:true}]}>
        <Select aria-label={words.userType} options={options.map(item=>({label:item.label,value:item.id}))}/>
      </Form.Item>
      <Button type="primary" htmlType="submit" loading={pending}>{words.submit}</Button>
    </Form>}
    <a href={loginPath}>{words.back}</a>
  </Card></main>;
}
